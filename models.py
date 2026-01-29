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

def seed_if_empty():
    with SessionLocal() as s:
        exists = s.execute(select(func.count(Regulation.id))).scalar_one()
        if exists:
            return

        r1 = Regulation(
            id=1,
            title="EU MRV 2025 Amendments",
            source="EU",
            jurisdiction="EU",
            category="Marine Ops;HSEQ",
            effective_date=date(2025, 1, 1),
            received_at=datetime(2025, 7, 15, 10, 0, 0),
            summary="Revised monitoring & reporting for CO₂ and CH₄.",
            status="In Progress",
        )
        r1.links = [
            RegulationLink(url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R-MRV", link_type="official", title="EUR-Lex: MRV 2025"),
            RegulationLink(url="https://example.com/mrv-guide.pdf", link_type="guidance", title="Practical MRV Guide (PDF)"),
        ]
        r1.actions = [
            Action(title="Update data pipeline for CH₄", description="Include methane reporting in MRV extracts", status="In Progress", assignee="A. Smith;J. Kim", due_date=date(2025, 8, 20)),
            Action(title="Crew circular MRV changes", description="Ops circular outlining new monitoring plan", status="Planned", assignee="M. Lopez", due_date=date(2025, 8, 25)),
        ]

        r2 = Regulation(
            id=2,
            title="IMO MARPOL Annex VI NOx Tier III Guidance",
            source="IMO",
            jurisdiction="Global",
            category="Technical;HSEQ",
            effective_date=date(2025, 6, 30),
            received_at=datetime(2025, 7, 20, 9, 0, 0),
            summary="Clarifies EIAPP documentation and testing windows for retrofits.",
            status="Open",
        )
        r2.links = [RegulationLink(url="https://www.imo.org/en/OurWork/Environment/Pages/Air-Pollution.aspx", link_type="official", title="IMO Air Pollution")]
        r2.actions = [Action(title="Assess retrofit feasibility", description="Check Tier III compliance options for 2012-2016 builds", status="Planned", assignee="J. Kim;A. Smith", due_date=date(2025, 9, 10))]

        r3 = Regulation(
            id=3,
            title="USCG Policy Letter 25-04 on E-Navigation Logs",
            source="USCG",
            jurisdiction="USA",
            category="Marine Ops",
            effective_date=date(2025, 9, 1),
            received_at=datetime(2025, 7, 25, 12, 30, 0),
            summary="Accepts specific e-nav log formats with integrity checks.",
            status="N/A",
        )
        r3.links = [RegulationLink(url="https://www.dco.uscg.mil/Portals/9/CG-ENG/Policy", link_type="official", title="USCG Policy Portal")]

        s.add_all([r1, r2, r3])
        s.commit()

# Seed sample data once
seed_if_empty()
