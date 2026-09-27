"""Atlas - provider map ops. Standard layout: SQLAlchemy + JWT + roles.

DB: SQLite locally (./atlas.db), Postgres in prod via DATABASE_URL.
Roles: admin > manager > provider > consumer.
"""
from __future__ import annotations
import json
import math
import time
import uuid
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.templating import Jinja2Templates
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    create_token, get_current_user, get_optional_user,
    hash_password, require_roles, verify_password,
)
from app.db import get_db, init_db
from app.models_db import AuditRow, NoteRow, ProviderRow, ServiceRequestRow, User

Status = Literal["available", "busy", "closed"]

BASE_DIR = Path(__file__).resolve().parent.parent
app = FastAPI(title="Atlas")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# ---------- light rate limiting (per-IP sliding window, public write endpoints) ----------
_RL: dict[str, list[float]] = {}

def _rl_check(request: Request, bucket: str, max_n: int, window_s: int):
    now = time.time()
    # behind the Pxxl edge proxy (uvicorn --proxy-headers) every client would
    # otherwise share one IP; prefer the first X-Forwarded-For entry.
    fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    ip = fwd or (request.client.host if request.client else "?")
    k = f"{ip}:{bucket}"
    hits = [t for t in _RL.get(k, []) if now - t < window_s]
    if len(hits) >= max_n:
        raise HTTPException(429, "too many requests, slow down")
    hits.append(now)
    _RL[k] = hits

def limit_login(request: Request): _rl_check(request, "login", 20, 60)
def limit_register(request: Request): _rl_check(request, "register", 10, 60)
def limit_request(request: Request): _rl_check(request, "request", 30, 60)
def limit_board(request: Request): _rl_check(request, "board", 30, 60)


# ---------- schemas ----------
class Provider(BaseModel):
    id: str
    name: str
    email: str = ""
    phone: str = ""
    lat: float
    lng: float
    area: str = ""
    status: str = "available"
    services: List[str] = []
    updated_at: float = 0


class ProviderIn(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    area: str = ""
    status: Status = "available"
    services: List[str] = []


class ProviderPatch(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    area: Optional[str] = None
    status: Optional[Status] = None
    services: Optional[List[str]] = None


class PolygonIn(BaseModel):
    polygon: List[List[float]]
    status: Optional[str] = None


class RequestIn(BaseModel):
    name: str
    phone: str = ""
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    note: str = ""


class RegisterIn(BaseModel):
    name: str
    email: str
    password: str
    role: Optional[str] = "consumer"


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    role: str
    provider_id: str = ""
    is_active: bool = True


class RolePatch(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    provider_id: Optional[str] = None


# ---------- helpers ----------
def row_to_provider(r: ProviderRow) -> Provider:
    try:
        services = json.loads(r.services_json or "[]")
    except Exception:
        services = []
    return Provider(id=r.id, name=r.name, email=r.email or "", phone=r.phone or "",
                    lat=r.lat, lng=r.lng, area=r.area or "", status=r.status,
                    services=services, updated_at=r.updated_at or 0)


def audit(db: Session, actor: str, action: str, target: str, meta: str = ""):
    db.add(AuditRow(actor=actor or "", action=action, target=target, meta=meta, created_at=time.time()))


def haversine_km(a_lat, a_lng, b_lat, b_lng) -> float:
    R = 6371.0
    dlat = math.radians(b_lat - a_lat)
    dlng = math.radians(b_lng - a_lng)
    s = math.sin(dlat / 2) ** 2 + math.cos(math.radians(a_lat)) * math.cos(math.radians(b_lat)) * math.sin(dlng / 2) ** 2
    return 2 * R * math.asin(math.sqrt(s))


def point_in_polygon(lat: float, lng: float, poly: List[List[float]]) -> bool:
    # ray casting, poly = [[lat,lng],...], x=lng, y=lat
    inside = False
    n = len(poly)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        yi, xi = poly[i][0], poly[i][1]
        yj, xj = poly[j][0], poly[j][1]
        if ((yi > lat) != (yj > lat)):
            # x of edge at this latitude; (yj - yi) != 0 guaranteed by the branch above
            xinters = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lng < xinters:
                inside = not inside
        j = i
    return inside


def seed(db: Session):
    if db.query(User).count() == 0:
        users = [
            ("Admin", "admin@atlas.local", "admin123", "admin"),
            ("Manager", "manager@atlas.local", "manager123", "manager"),
            ("Demo Provider", "provider@atlas.local", "provider123", "provider"),
        ]
        for name, email, pw, role in users:
            db.add(User(email=email, name=name, hashed_password=hash_password(pw), role=role))
        db.commit()
    if db.query(ProviderRow).count() == 0:
        seed_p = [
            ("Adaeze Okafor", "adaeze@atlas.demo", "0803 111 0101", 6.5244, 3.3792, "Ikeja", "available", ["pos", "onboarding"]),
            ("Tunde Bakare", "tunde@atlas.demo", "0803 111 0102", 6.6018, 3.3515, "Ikeja", "busy", ["settlement"]),
            ("Chiamaka Eze", "chiamaka@atlas.demo", "0803 111 0103", 6.4281, 3.4219, "Victoria Island", "available", ["pos", "dispute"]),
            ("Ibrahim Musa", "ibrahim@atlas.demo", "0803 111 0104", 6.4698, 3.5852, "Ajah", "available", ["kyc"]),
            ("Ngozi Adeyemi", "ngozi@atlas.demo", "0803 111 0105", 6.4474, 3.3903, "Surulere", "closed", ["pos"]),
            ("Emeka Nwosu", "emeka@atlas.demo", "0803 111 0106", 6.5833, 3.3667, "Agege", "available", ["terminal", "support"]),
            ("Fatima Bello", "fatima@atlas.demo", "0803 111 0107", 6.4969, 3.3445, "Yaba", "busy", ["onboarding", "training"]),
            ("Olumide Ajayi", "olumide@atlas.demo", "0803 111 0108", 6.5536, 3.3669, "Ogba", "available", ["dispute", "settlement"]),
            ("Sarah Mensah", "sarah@atlas.demo", "0803 111 0109", 6.4549, 3.3946, "Lagos Island", "available", ["pos", "kyc"]),
            ("Yusuf Abdullahi", "yusuf@atlas.demo", "0803 111 0110", 6.5000, 3.3000, "Festac", "busy", ["support"]),
            ("Kelechi Obi", "kelechi@atlas.demo", "0803 111 0111", 6.6100, 3.4100, "Ojodu", "available", ["terminal"]),
            ("Aisha Sule", "aisha@atlas.demo", "0803 111 0112", 6.4000, 3.4500, "Lekki", "closed", ["onboarding"]),
        ]
        for name, email, phone, lat, lng, area, st, sv in seed_p:
            db.add(ProviderRow(id=uuid.uuid4().hex[:8], name=name, email=email, phone=phone,
                               lat=lat, lng=lng, area=area, status=st,
                               services_json=json.dumps(sv), updated_at=time.time()))
        db.commit()
        # link demo provider user to first available provider
        first = db.query(ProviderRow).first()
        u = db.query(User).filter(User.email == "provider@atlas.local").first()
        if first and u:
            u.provider_id = first.id
            db.commit()


@app.on_event("startup")
def _startup():
    init_db()
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()


# ensure tables + seed exist even without lifespan (tests, import)
try:
    init_db()
    from app.db import SessionLocal as _SL
    _db = _SL()
    try:
        seed(_db)
    finally:
        _db.close()
except Exception:
    pass


# ---------- pages ----------
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health():
    return {"ok": True}


# ---------- auth ----------
@app.post("/api/auth/register", response_model=UserOut)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db),
             me=Depends(get_optional_user), _rl=Depends(limit_register)):
    email = body.email.strip().lower()
    if not email or not body.password or len(body.password) < 6:
        raise HTTPException(400, "valid email + 6-char password required")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(400, "email already registered")
    role = "consumer"
    if me and me.is_active and me.role == "admin" and body.role in ("admin", "manager", "provider", "consumer"):
        role = body.role
    u = User(email=email, name=body.name.strip(), hashed_password=hash_password(body.password), role=role)
    db.add(u)
    db.commit()
    db.refresh(u)
    return UserOut(id=u.id, email=u.email, name=u.name, role=u.role, provider_id=u.provider_id, is_active=u.is_active)


@app.post("/api/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends(), request: Request = None, db: Session = Depends(get_db),
          _rl=Depends(limit_login)):
    email = form.username.strip().lower()
    u = db.query(User).filter(User.email == email).first()
    if not u or not verify_password(form.password, u.hashed_password):
        raise HTTPException(401, "invalid credentials")
    if not u.is_active:
        raise HTTPException(403, "account disabled")
    return {"access_token": create_token(u.email, u.role, u.name), "token_type": "bearer",
            "role": u.role, "name": u.name, "email": u.email}


@app.get("/api/auth/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role,
                   provider_id=user.provider_id or "", is_active=user.is_active)


class PasswordIn(BaseModel):
    old: str
    new: str


@app.post("/api/auth/password")
def change_password(body: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    u = db.query(User).filter(User.id == user.id).first()
    if not u or not verify_password(body.old, u.hashed_password):
        raise HTTPException(400, "current password is wrong")
    if not body.new or len(body.new) < 6:
        raise HTTPException(400, "new password needs 6+ characters")
    u.hashed_password = hash_password(body.new)
    db.commit()
    return {"ok": True}


@app.get("/api/users", response_model=List[UserOut])
def list_users(user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.id).all()
    return [UserOut(id=r.id, email=r.email, name=r.name, role=r.role, provider_id=r.provider_id or "", is_active=r.is_active) for r in rows]


@app.patch("/api/users/{uid}", response_model=UserOut)
def patch_user(uid: int, body: RolePatch, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    r = db.query(User).filter(User.id == uid).first()
    if not r:
        raise HTTPException(404, "user not found")
    if r.id == user.id and ((body.role and body.role != "admin") or body.is_active is False):
        raise HTTPException(400, "you cannot demote or deactivate yourself")
    if body.role in ("admin", "manager", "provider", "consumer"):
        r.role = body.role
    if body.is_active is not None:
        r.is_active = body.is_active
    if body.provider_id is not None:
        r.provider_id = body.provider_id
    db.commit()
    db.refresh(r)
    return UserOut(id=r.id, email=r.email, name=r.name, role=r.role, provider_id=r.provider_id or "", is_active=r.is_active)


# ---------- providers ----------
@app.get("/api/providers", response_model=List[Provider])
def list_providers(q: str = "", status: str = "", area: str = "", db: Session = Depends(get_db)):
    rows = db.query(ProviderRow).all()
    out = [row_to_provider(r) for r in rows]
    if q:
        ql = q.lower()
        out = [p for p in out if ql in p.name.lower() or ql in p.area.lower()
               or ql in p.email.lower() or any(ql in s.lower() for s in p.services)]
    if status and status != "all":
        out = [p for p in out if p.status == status]
    if area and area != "all":
        out = [p for p in out if p.area == area]
    return sorted(out, key=lambda p: p.name.lower())


@app.post("/api/providers", response_model=Provider, status_code=201)
def create_provider(body: ProviderIn, user: User = Depends(require_roles("admin", "manager")),
                    db: Session = Depends(get_db)):
    r = ProviderRow(id=uuid.uuid4().hex[:8], name=body.name.strip(), email=body.email.strip(),
                    phone=body.phone.strip(), lat=body.lat, lng=body.lng, area=body.area.strip(),
                    status=body.status, services_json=json.dumps(body.services or []), updated_at=time.time())
    db.add(r)
    audit(db, user.email, "provider.create", r.id, r.name)
    db.commit()
    db.refresh(r)
    return row_to_provider(r)


@app.patch("/api/providers/{pid}", response_model=Provider)
def update_provider(pid: str, body: ProviderPatch, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    r = db.query(ProviderRow).filter(ProviderRow.id == pid).first()
    if not r:
        raise HTTPException(404, "provider not found")
    if hasattr(body, "model_dump"):
        data = body.model_dump(exclude_unset=True, exclude_none=True)
    else:
        data = body.dict(exclude_unset=True, exclude_none=True)
    # provider role: own record only, limited fields
    if user.role == "provider":
        if (user.provider_id or "") != pid:
            raise HTTPException(403, "providers can only edit their own record")
        data = {k: v for k, v in data.items() if k in ("status", "lat", "lng", "phone")}
    elif user.role not in ("admin", "manager"):
        raise HTTPException(403, "manager role required")
    if "lat" in data and not (-90 <= data["lat"] <= 90):
        raise HTTPException(422, "lat out of range")
    if "lng" in data and not (-180 <= data["lng"] <= 180):
        raise HTTPException(422, "lng out of range")
    for k, v in data.items():
        if k == "services":
            r.services_json = json.dumps(v or [])
        else:
            setattr(r, k, v)
    r.updated_at = time.time()
    audit(db, user.email, "provider.update", pid, json.dumps(data)[:500])
    db.commit()
    db.refresh(r)
    return row_to_provider(r)


@app.delete("/api/providers/{pid}")
def delete_provider(pid: str, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    r = db.query(ProviderRow).filter(ProviderRow.id == pid).first()
    if not r:
        raise HTTPException(404, "provider not found")
    db.delete(r)
    audit(db, user.email, "provider.delete", pid, "")
    db.commit()
    return {"ok": True}


@app.post("/api/providers/within", response_model=List[Provider])
def providers_within(body: PolygonIn, db: Session = Depends(get_db)):
    if len(body.polygon) > 5000:
        raise HTTPException(400, "polygon too large (max 5000 points)")
    rows = db.query(ProviderRow).all()
    out = [row_to_provider(r) for r in rows if point_in_polygon(r.lat, r.lng, body.polygon)]
    if body.status and body.status != "all":
        out = [p for p in out if p.status == body.status]
    return out


class BulkIn(BaseModel):
    providers: List[ProviderIn]


@app.post("/api/providers/bulk")
def bulk_create(body: BulkIn, user: User = Depends(require_roles("admin", "manager")),
                db: Session = Depends(get_db)):
    if not body.providers or len(body.providers) > 2000:
        raise HTTPException(400, "send 1-2000 providers")
    ids = []
    for b in body.providers:
        r = ProviderRow(id=uuid.uuid4().hex[:8], name=b.name.strip(), email=b.email.strip(),
                        phone=b.phone.strip(), lat=b.lat, lng=b.lng, area=b.area.strip(),
                        status=b.status, services_json=json.dumps(b.services or []), updated_at=time.time())
        db.add(r)
        ids.append(r.id)
    audit(db, user.email, "provider.bulk", "", str(len(ids)))
    db.commit()
    return {"created": len(ids), "ids": ids}


# ---------- consumer requests (public create with throttle, staff read) ----------
@app.post("/api/requests")
def create_request(body: RequestIn, request: Request, db: Session = Depends(get_db),
                   _rl=Depends(limit_request)):
    rows = db.query(ProviderRow).all()
    cands = [r for r in rows if r.status == "available"] or rows
    if not cands:
        raise HTTPException(404, "no providers")
    ranked = sorted(cands, key=lambda p: haversine_km(body.lat, body.lng, p.lat, p.lng))
    best = ranked[0]
    dist = haversine_km(body.lat, body.lng, best.lat, best.lng)
    rec = ServiceRequestRow(name=body.name, phone=body.phone, lat=body.lat, lng=body.lng,
                            note=body.note, assigned_provider_id=best.id,
                            distance_km=round(dist, 2), status="routed", created_at=time.time())
    db.add(rec)
    audit(db, body.name, "request.routed", best.id, f"{dist:.1f}km")
    db.commit()
    bp = row_to_provider(best)
    alts = [row_to_provider(r) for r in ranked[1:3]]
    return {"assigned": bp, "distance_km": round(dist, 2), "alternates": alts,
            "message": f"Routed to {bp.name} ({bp.area}, {dist:.1f} km)"}


@app.get("/api/requests")
def list_requests(user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    rows = db.query(ServiceRequestRow).order_by(ServiceRequestRow.id.desc()).limit(100).all()
    return [{"id": r.id, "name": r.name, "phone": r.phone, "lat": r.lat, "lng": r.lng,
             "note": r.note, "assigned": r.assigned_provider_id, "km": r.distance_km,
             "status": r.status, "at": r.created_at} for r in rows]


class RequestPatch(BaseModel):
    status: Optional[str] = None
    assigned_provider_id: Optional[str] = None


@app.patch("/api/requests/{rid}")
def patch_request(rid: int, body: RequestPatch, user: User = Depends(require_roles("admin", "manager")),
                  db: Session = Depends(get_db)):
    r = db.query(ServiceRequestRow).filter(ServiceRequestRow.id == rid).first()
    if not r:
        raise HTTPException(404, "request not found")
    if body.status in ("routed", "accepted", "done", "closed"):
        r.status = body.status
    if body.assigned_provider_id:
        exists = db.query(ProviderRow).filter(ProviderRow.id == body.assigned_provider_id).first()
        if not exists:
            raise HTTPException(404, "provider not found")
        r.assigned_provider_id = body.assigned_provider_id
    audit(db, user.email, "request.update", str(rid), (body.status or "") + " " + (body.assigned_provider_id or ""))
    db.commit()
    return {"ok": True}


@app.get("/api/stats")
def stats(db: Session = Depends(get_db)):
    rows = db.query(ProviderRow).all()
    by_status: dict[str, int] = {}
    by_area: dict[str, int] = {}
    for r in rows:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_area[r.area or "—"] = by_area.get(r.area or "—", 0) + 1
    n_req = db.query(ServiceRequestRow).count()
    recent = db.query(AuditRow).order_by(AuditRow.id.desc()).limit(8).all()
    return {"total": len(rows), "by_status": by_status, "by_area": by_area,
            "requests": n_req,
            "recent": [{"actor": x.actor, "action": x.action, "target": x.target, "at": x.created_at} for x in recent]}


@app.get("/api/areas")
def areas(db: Session = Depends(get_db)):
    return sorted({r.area for r in db.query(ProviderRow).all() if r.area})


@app.get("/api/audit")
def recent_audit(user: User = Depends(require_roles("admin", "manager")), db: Session = Depends(get_db)):
    rows = db.query(AuditRow).order_by(AuditRow.id.desc()).limit(100).all()
    return [{"id": r.id, "actor": r.actor, "action": r.action, "target": r.target, "meta": r.meta, "at": r.created_at} for r in rows]


class NoteIn(BaseModel):
    text: str


@app.get("/api/board")
def list_notes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(NoteRow).order_by(NoteRow.id.desc()).limit(100).all()
    return [{"id": r.id, "author": r.author, "text": r.text, "at": r.created_at} for r in rows]


@app.post("/api/board", status_code=201)
def post_note(body: NoteIn, request: Request, user: User = Depends(get_current_user),
              db: Session = Depends(get_db), _rl=Depends(limit_board)):
    text = (body.text or "").strip()
    if not text or len(text) > 500:
        raise HTTPException(400, "note needs 1-500 characters")
    r = NoteRow(author=user.name or user.email, text=text, created_at=time.time())
    db.add(r)
    db.commit()
    db.refresh(r)
    return {"id": r.id, "author": r.author, "text": r.text, "at": r.created_at}


@app.delete("/api/board/{nid}")
def delete_note(nid: int, user: User = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    r = db.query(NoteRow).filter(NoteRow.id == nid).first()
    if not r:
        raise HTTPException(404, "note not found")
    db.delete(r)
    db.commit()
    return {"ok": True}
