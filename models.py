"""
models.py — SQLAlchemy models and data helpers
- Defines Regulation, RegulationLink, Action, EmailIngest, KvStore
- Sets up engine, SessionLocal, Base
- Includes seed_if_empty() with sample data
"""

from datetime import date, datetime
from typing import List, Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Date, DateTime, ForeignKey, select, func
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, selectinload

from config import DATABASE_URL, DEPARTMENTS, REG_STATUS_OPTIONS

# --- SQLAlchemy setup ---
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# --- Helpers (shared with UI/agent) ---
def split_multi(val: Optional[str]) -> List[str]:
    """Split 'a;b, c | d' into ['a','b','c','d'] (trimmed, unique order kept)."""
    if not val:
        return []
    raw = str(val)
    for sep in ["|", ","]:
        raw = raw.replace(sep, ";")
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    seen = set()
    out: List[str] = []
    for p in parts:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out

def join_multi(items: List[str]) -> str:
    """Join items into 'a;b;c' unique (case-insensitive) preserving order."""
    seen = set()
    out: List[str] = []
    for i in items:
        if not i:
            continue
        v = i.strip()
        if not v:
            continue
        k = v.lower()
        if k not in seen:
            seen.add(k)
            out.append(v)
    return ";".join(out)

def normalize_departments(items: List[str]) -> List[str]:
    """Filter to allowed departments and keep canonical casing from DEPARTMENTS."""
    allowed = {d.lower(): d for d in DEPARTMENTS}
    out: List[str] = []
    seen = set()
    for x in items:
        if not x:
            continue
        k = x.strip().lower()
        if k in allowed and k not in seen:
            seen.add(k)
            out.append(allowed[k])
    return out

# --- Models ---
class Regulation(Base):
    __tablename__ = "regulations"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    source = Column(String)
    jurisdiction = Column(String)
    # DB column stays 'category', UI label: Department (supports multi-values "A;B;C")
    category = Column(String)
    effective_date = Column(Date)
    received_at = Column(DateTime, default=datetime.utcnow)
    summary = Column(Text)
    status = Column(String, default="N/A")  # Open | In Progress | Closed | N/A
    # Semicolon-separated fleet types this regulation applies to, e.g. "Container Vessels;Bulk Carriers"
    fleet_tags = Column(Text, nullable=True)

    links = relationship("RegulationLink", back_populates="regulation", cascade="all, delete-orphan")
    actions = relationship("Action", back_populates="regulation", cascade="all, delete-orphan")

class RegulationLink(Base):
    __tablename__ = "regulation_links"
    id = Column(Integer, primary_key=True)
    regulation_id = Column(Integer, ForeignKey("regulations.id"), index=True)
    url = Column(Text, nullable=False)
    link_type = Column(String)   # official | guidance | news | pdf
    title = Column(Text)
    regulation = relationship("Regulation", back_populates="links")

class Action(Base):
    __tablename__ = "actions"
    id = Column(Integer, primary_key=True)
    regulation_id = Column(Integer, ForeignKey("regulations.id"), index=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(String, default="Planned")  # Planned | In Progress | Done | Blocked
    assignee = Column(String)  # multi: "A. Smith;M. Lopez"
    due_date = Column(Date)
    completed_at = Column(DateTime)
    regulation = relationship("Regulation", back_populates="actions")

class EmailIngest(Base):
    __tablename__ = "email_ingest"
    id = Column(Integer, primary_key=True)
    internet_message_id = Column(String, unique=True, index=True)
    regulation_id = Column(Integer, ForeignKey("regulations.id"))
    received_at = Column(DateTime)
    folder = Column(String)
    subject = Column(Text)

class KvStore(Base):
    __tablename__ = "kv_store"
    key = Column(String, primary_key=True)
    value = Column(Text)

# --- DB init & seed ---
Base.metadata.create_all(engine)

# Auto-migrate: add fleet_tags column if it doesn't exist yet (SQLite safe)
with engine.connect() as _conn:
    _cols = [row[1] for row in _conn.execute(
        __import__("sqlalchemy").text("PRAGMA table_info(regulations)")
    )]
    if "fleet_tags" not in _cols:
        _conn.execute(__import__("sqlalchemy").text(
            "ALTER TABLE regulations ADD COLUMN fleet_tags TEXT"
        ))
        _conn.commit()


