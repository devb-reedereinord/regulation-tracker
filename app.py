import os
from datetime import date, datetime
from typing import List, Optional

import pandas as pd
import streamlit as st
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, Date, DateTime, ForeignKey, select, func
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from sqlalchemy.exc import ProgrammingError

# --------------------------- Config ---------------------------
DEFAULT_DB = "sqlite:///regtracker.db"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DB)
engine = create_engine(DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

# --------------------------- Models ---------------------------
class Regulation(Base):
    __tablename__ = "regulations"
    id = Column(Integer, primary_key=True)
    title = Column(Text, nullable=False)
    source = Column(String)
    jurisdiction = Column(String)
    category = Column(String)
    effective_date = Column(Date)
    received_at = Column(DateTime, default=datetime.utcnow)
    summary = Column(Text)
    status = Column(String, default="Open")  # Open | In Progress | Closed

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
    assignee = Column(String)
    due_date = Column(Date)
    completed_at = Column(DateTime)

    regulation = relationship("Regulation", back_populates="actions")

# --------------------------- DB init & seed ---------------------------
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
            category="Environmental",
            effective_date=date(2025,1,1),
            received_at=datetime(2025,7,15,10,0,0),
            summary="Revised monitoring & reporting for CO₂ and CH₄.",
            status="In Progress",
        )
        r1.links = [
            RegulationLink(url="https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32025R-MRV", link_type="official", title="EUR-Lex: MRV 2025"),
            RegulationLink(url="https://example.com/mrv-guide.pdf", link_type="guidance", title="Practical MRV Guide (PDF)"),
        ]
        r1.actions = [
            Action(title="Update data pipeline for CH₄", description="Include methane reporting in MRV extracts", status="In Progress", assignee="A. Smith", due_date=date(2025,8,20)),
            Action(title="Crew circular MRV changes", description="Ops circular outlining new monitoring plan", status="Planned", assignee="M. Lopez", due_date=date(2025,8,25)),
        ]
        r2 = Regulation(
            id=2,
            title="IMO MARPOL Annex VI NOx Tier III Guidance",
            source="IMO",
            jurisdiction="Global",
            category="Technical",
            effective_date=date(2025,6,30),
            received_at=datetime(2025,7,20,9,0,0),
            summary="Clarifies EIAPP documentation and testing windows for retrofits.",
            status="Open",
        )
        r2.links = [RegulationLink(url="https://www.imo.org/en/OurWork/Environment/Pages/Air-Pollution.aspx", link_type="official", title="IMO Air Pollution")]
        r2.actions = [Action(title="Assess retrofit feasibility", description="Check Tier III compliance options for 2012-2016 builds", status="Planned", assignee="J. Kim", due_date=date(2025,9,10))]
        r3 = Regulation(
            id=3,
            title="USCG Policy Letter 25-04 on E-Navigation Logs",
            source="USCG",
            jurisdiction="USA",
            category="Navigation",
            effective_date=date(2025,9,1),
            received_at=datetime(2025,7,25,12,30,0),
            summary="Accepts specific e-nav log formats with integrity checks.",
            status="Open",
        )
        r3.links = [RegulationLink(url="https://www.dco.uscg.mil/Portals/9/CG-ENG/Policy", link_type="official", title="USCG Policy Portal")]

        s.add_all([r1, r2, r3])
        s.commit()

seed_if_empty()

# --------------------------- UI ---------------------------
st.set_page_config(page_title="Regulation Tracker (PoC)", layout="wide")
st.title("Regulation Tracker")

with st.sidebar:
    st.subheader("Filters")
    q = st.text_input("Search (title/summary/jurisdiction)")
    # dynamic options
    with SessionLocal() as s:
        sources = [r[0] for r in s.execute(select(Regulation.source).distinct()).all() if r[0]]
        categories = [r[0] for r in s.execute(select(Regulation.category).distinct()).all() if r[0]]
    source = st.selectbox("Source", options=["All"] + sources)
    status = st.selectbox("Status", options=["All", "Open", "In Progress", "Closed"])
    category = st.selectbox("Category", options=["All"] + categories)

# fetch filtered list
with SessionLocal() as s:
    stmt = select(Regulation)
    regs = s.execute(stmt).scalars().all()

# client-side filter for simplicity
filtered: List[Regulation] = []
ql = (q or "").lower()
for r in regs:
    if ql:
        if not ((r.title or "").lower().find(ql) >= 0 or (r.summary or "").lower().find(ql) >= 0 or (r.jurisdiction or "").lower().find(ql) >= 0):
            continue
    if source != "All" and r.source != source:
        continue
    if status != "All" and r.status != status:
        continue
    if category != "All" and r.category != category:
        continue
    filtered.append(r)

left, right = st.columns([7,5])

with left:
    st.subheader("Regulations")
    df = pd.DataFrame([
        {
            "ID": r.id,
            "Title": r.title,
            "Source": r.source,
            "Category": r.category,
            "Effective": r.effective_date,
            "Status": r.status,
        }
        for r in filtered
    ])
    st.dataframe(df, use_container_width=True, hide_index=True)

    ids = [r.id for r in filtered]
    titles = [f"#{r.id} — {r.title[:80]}" for r in filtered]
    selected_label = st.selectbox("Select a regulation", options=["(none)"] + titles)
    selected_id: Optional[int] = None
    if selected_label != "(none)":
        idx = titles.index(selected_label)
        selected_id = ids[idx]

with right:
    st.subheader("Details & Actions")
    if not selected_id:
        st.info("Select a regulation on the left to view and edit.")
    else:
        with SessionLocal() as s:
            reg = s.get(Regulation, selected_id)
            if not reg:
                st.error("Not found.")
            else:
                st.markdown(f"### {reg.title}")
                st.caption(f"{reg.source or '-'} · {reg.jurisdiction or '-'} · Effective {reg.effective_date or '-'}")
                st.write(reg.summary or "")

                # edit status
                new_status = st.selectbox("Status", options=["Open", "In Progress", "Closed"], index=["Open","In Progress","Closed"].index(reg.status or "Open"))
                if new_status != reg.status:
                    reg.status = new_status
                    s.add(reg)
                    s.commit()
                    st.success("Status updated")

                st.markdown("#### Relevant Links")
                if not reg.links:
                    st.write("No links attached.")
                else:
                    for l in reg.links:
                        st.markdown(f"- [{l.title or l.url}]({l.url})  ")

                st.markdown("#### Actions")
                # list actions
                if not reg.actions:
                    st.write("No actions yet.")
                else:
                    for a in sorted(reg.actions, key=lambda x: (x.due_date or date.max)):
                        with st.expander(f"{a.title} — {a.status}"):
                            c1,c2,c3 = st.columns([2,1,1])
                            with c1:
                                new_title = st.text_input("Title", value=a.title, key=f"t_{a.id}")
                                new_desc = st.text_area("Description", value=a.description or "", key=f"d_{a.id}")
                            with c2:
                                new_status = st.selectbox("Status", ["Planned","In Progress","Done","Blocked"], index=["Planned","In Progress","Done","Blocked"].index(a.status or "Planned"), key=f"s_{a.id}")
                                new_assignee = st.text_input("Assignee", value=a.assignee or "", key=f"as_{a.id}")
                            with c3:
                                new_due = st.date_input("Due date", value=a.due_date or date.today(), key=f"dd_{a.id}")
                                done = st.checkbox("Mark done", value=(a.status=="Done"), key=f"ck_{a.id}")
                            save = st.button("Save", key=f"save_{a.id}")
                            delete = st.button("Delete", type="secondary", key=f"del_{a.id}")
                            if save:
                                a.title = new_title
                                a.description = new_desc
                                a.status = "Done" if done else new_status
                                a.assignee = new_assignee
                                a.due_date = new_due
                                a.completed_at = datetime.utcnow() if a.status=="Done" else None
                                s.add(a)
                                s.commit()
                                st.success("Saved")
                            if delete:
                                s.delete(a)
                                s.commit()
                                st.warning("Deleted")

                st.divider()
                st.markdown("#### Add Action")
                with st.form("add_action"):
                    atitle = st.text_input("Title", value="New action")
                    adesc = st.text_area("Description", value="")
                    aassignee = st.text_input("Assignee", value="")
                    adue = st.date_input("Due date", value=date.today())
                    submitted = st.form_submit_button("Add")
                    if submitted:
                        new_a = Action(regulation_id=reg.id, title=atitle, description=adesc, assignee=aassignee, due_date=adue)
                        s.add(new_a)
                        s.commit()
                        st.success("Action added")


st.caption("DB: {}".format(DATABASE_URL))
