"""JWT auth + roles. No native deps (pbkdf2 + PyJWT)."""
from __future__ import annotations
import hashlib
import hmac
import os
import secrets
import time

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

SECRET_KEY = os.getenv("SECRET_KEY", "atlas-dev-secret-change-me")
ALGORITHM = "HS256"
EXPIRE_HOURS = 12

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def hash_password(pw: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, hexdk = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
        return hmac.compare_digest(dk.hex(), hexdk)
    except Exception:
        return False


def create_token(sub: str, role: str, name: str) -> str:
    now = int(time.time())
    payload = {"sub": sub, "role": role, "name": name, "iat": now, "exp": now + EXPIRE_HOURS * 3600}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])


def get_db_dep():
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(token: str = Depends(oauth2), db: Session = Depends(get_db_dep)):
    from app.models_db import User
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    try:
        data = decode_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="invalid token")
    user = db.query(User).filter(User.email == data.get("sub")).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="account disabled")
    return user


def get_optional_user(token: str = Depends(oauth2), db: Session = Depends(get_db_dep)):
    if not token:
        return None
    try:
        from app.models_db import User
        data = decode_token(token)
        return db.query(User).filter(User.email == data.get("sub")).first()
    except Exception:
        return None


def require_roles(*roles: str):
    allowed = set(roles)
    def _check(user=Depends(get_current_user)):
        if user.role == "admin":
            return user
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail=f"requires role: {','.join(allowed)}")
        return user
    return _check
