"""SQLAlchemy tables. Postgres-compatible, SQLite-friendly."""
from __future__ import annotations
import time
from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    hashed_password: Mapped[str] = mapped_column(String(512))
    role: Mapped[str] = mapped_column(String(32), default="consumer")  # admin|manager|provider|consumer
    provider_id: Mapped[str] = mapped_column(String(32), default="", index=True)  # link to providers.id
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class ProviderRow(Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    lat: Mapped[float] = mapped_column(Float, index=True)
    lng: Mapped[float] = mapped_column(Float, index=True)
    area: Mapped[str] = mapped_column(String(128), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="available", index=True)
    services_json: Mapped[str] = mapped_column(Text, default="[]")
    owner_user_id: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)


class ServiceRequestRow(Base):
    __tablename__ = "requests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(64), default="")
    lat: Mapped[float] = mapped_column(Float, default=0)
    lng: Mapped[float] = mapped_column(Float, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    assigned_provider_id: Mapped[str] = mapped_column(String(32), default="")
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(32), default="routed")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class AuditRow(Base):
    __tablename__ = "audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64), default="")
    target: Mapped[str] = mapped_column(String(64), default="")
    meta: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class NoteRow(Base):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    author: Mapped[str] = mapped_column(String(255), default="")
    text: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
