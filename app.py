import streamlit as st
import pandas as pd
from sqlalchemy import select
from datetime import datetime, date
from difflib import SequenceMatcher

from models import SessionLocal, Regulation, RegulationLink, KvStore, normalize_departments, join_multi

from web_monitor import discover_articles
from web_ingest import ingest_web_article, discover_and_preview_web_articles

try:
    from agent import ingest_shared_mailbox, start_device_flow, complete_device_flow, get_token_cache_string, resummary_with_ai
    from config import SHARED_MAILBOX, GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET, EDIT_PASSWORD
    _EMAIL_IMPORTS_OK = True
    _EMAIL_IMPORT_ERR = ""
except Exception as _e:
    _EMAIL_IMPORTS_OK = False
    _EMAIL_IMPORT_ERR = str(_e)
    SHARED_MAILBOX = ""
    GRAPH_TENANT_ID = GRAPH_CLIENT_ID = GRAPH_CLIENT_SECRET = ""
    try:
        from config import EDIT_PASSWORD
    except Exception:
        EDIT_PASSWORD = ""

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RegTracker",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state defaults ────────────────────────────────────────────────────
st.session_state.setdefault("edit_unlocked", False)

# ── Global CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Font + base */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

/* Hide Streamlit default header chrome */
#MainMenu, footer { visibility: hidden; }
header[data-testid="stHeader"] { background: transparent; }

/* ── Global white text ── */
.stApp, .stApp * {
    color: #ffffff !important;
}

/* Page background */
.stApp { background: #0f1117; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #161b27;
    border-right: 1px solid #1e2535;
}
[data-testid="stSidebar"] * { color: #ffffff !important; }
[data-testid="stSidebar"] .stMarkdown h2 {
    color: #60a5fa !important;
    font-size: 0.75rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    font-weight: 700;
    margin-top: 1.2rem;
}

/* Metric cards */
[data-testid="metric-container"] {
    background: #161b27;
    border: 1px solid #1e2535;
    border-radius: 12px;
    padding: 1rem 1.5rem;
}
[data-testid="metric-container"] label { color: #cbd5e1 !important; font-size: 0.75rem; letter-spacing: 0.05em; text-transform: uppercase; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #ffffff !important; font-size: 2rem; font-weight: 700; }

/* Section headers */
h1 { color: #ffffff !important; font-size: 1.6rem !important; font-weight: 700 !important; }
h2 { color: #ffffff !important; font-size: 1.15rem !important; font-weight: 600 !important; border-bottom: 1px solid #1e2535; padding-bottom: 0.4rem; }
h3 { color: #e2e8f0 !important; font-size: 0.9rem !important; font-weight: 600 !important; }

/* Paragraphs, captions, labels */
p, span, div, label { color: #ffffff !important; }
[data-testid="stCaption"], [data-testid="stCaption"] * { color: #cbd5e1 !important; }

/* Selectbox, text input labels + values */
.stSelectbox label, .stTextInput label, .stTextArea label,
.stNumberInput label, .stDateInput label, .stMultiSelect label { color: #ffffff !important; }
.stSelectbox [data-baseweb="select"] * { color: #ffffff !important; }
.stMultiSelect [data-baseweb="tag"] * { color: #ffffff !important; }

/* Radio buttons */
.stRadio label, .stRadio div { color: #ffffff !important; }

/* Expander title */
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color: #ffffff !important; }

/* Buttons */
.stButton > button {
    background: #1d4ed8;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    font-size: 0.85rem;
    padding: 0.5rem 1.25rem;
    transition: background 0.2s;
}
.stButton > button:hover { background: #2563eb; }
.stButton > button[kind="secondary"] { background: #1e2535; color: #94a3b8; }

/* Dataframe */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
.stDataFrame thead tr th { background: #161b27 !important; color: #60a5fa !important; font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; }
.stDataFrame tbody tr:hover td { background: #1e2535 !important; }

/* Divider */
hr { border-color: #1e2535 !important; margin: 1.5rem 0; }

/* Form fields */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input,
.stSelectbox > div > div { background: #161b27 !important; border: 1px solid #1e2535 !important; color: #e2e8f0 !important; border-radius: 8px !important; }

/* Expander */
[data-testid="stExpander"] { background: #161b27; border: 1px solid #1e2535; border-radius: 10px; }

/* ── Date input field ── */
[data-testid="stDateInput"] input,
[data-baseweb="input"] input {
    background: #161b27 !important;
    color: #ffffff !important;
    border: 1px solid #1e2535 !important;
}

/* ── Date picker calendar popup ── */
/* Root container */
[data-baseweb="calendar"] {
    background-color: #1e2535 !important;
    border: 1px solid #334155 !important;
    border-radius: 10px !important;
}
/* Every element inside: dark bg, white text */
[data-baseweb="calendar"] div,
[data-baseweb="calendar"] table,
[data-baseweb="calendar"] thead,
[data-baseweb="calendar"] tbody,
[data-baseweb="calendar"] tr,
[data-baseweb="calendar"] td,
[data-baseweb="calendar"] th,
[data-baseweb="calendar"] span,
[data-baseweb="calendar"] button {
    background-color: #1e2535 !important;
    color: #ffffff !important;
    border-color: #334155 !important;
}
/* Day cells — transparent background on cell and ALL descendants */
[data-baseweb="calendar-day"],
[data-baseweb="calendar-day"] * {
    background-color: transparent !important;
    color: #ffffff !important;
}
/* Hover on day */
[data-baseweb="calendar-day"]:hover,
[data-baseweb="calendar-day"]:hover * {
    background-color: #334155 !important;
    border-radius: 50% !important;
}
/* Selected day — blue fill */
[data-baseweb="calendar-day"][aria-selected="true"],
[data-baseweb="calendar-day"][aria-selected="true"] * {
    background-color: #1d4ed8 !important;
    border-radius: 50% !important;
    color: #ffffff !important;
}
/* Today indicator — blue outline, transparent fill */
[data-baseweb="calendar-day"][aria-current="date"],
[data-baseweb="calendar-day"][aria-current="date"] * {
    background-color: transparent !important;
    border: 2px solid #60a5fa !important;
    border-radius: 50% !important;
    color: #ffffff !important;
}
/* Month/year header selects */
[data-baseweb="calendar"] select,
[data-baseweb="month-year-select-popover"],
[data-baseweb="month-year-select-popover"] * {
    background-color: #1e2535 !important;
    color: #ffffff !important;
}
/* Nav arrows */
[data-baseweb="calendar"] [data-baseweb="icon"] { fill: #ffffff !important; }

/* ── Dropdown popup dark theme ── */
[data-baseweb="popover"],
[data-baseweb="popover"] ul,
[data-baseweb="popover"] li {
    background-color: #1e2535 !important;
    border: 1px solid #334155 !important;
}
[data-baseweb="popover"] li *,
[data-baseweb="popover"] [role="option"] * {
    color: #ffffff !important;
    background-color: transparent !important;
}
[data-baseweb="popover"] li:hover,
[data-baseweb="popover"] [aria-selected="true"] {
    background-color: #334155 !important;
}

/* ── Selectbox trigger box ── */
[data-baseweb="select"] > div {
    background-color: #161b27 !important;
    border-color: #1e2535 !important;
}
[data-baseweb="select"] * {
    color: #ffffff !important;
}

/* Info / warning / success / error */
.stAlert { border-radius: 8px; border-left-width: 4px; }

/* Status badges */
.badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.04em;
}
.badge-open    { background: #7c3aed22; color: #a78bfa; border: 1px solid #7c3aed55; }
.badge-inprog  { background: #1d4ed822; color: #60a5fa; border: 1px solid #1d4ed855; }
.badge-closed  { background: #05966922; color: #34d399; border: 1px solid #05966955; }
.badge-na      { background: #37415122; color: #94a3b8; border: 1px solid #37415155; }
/* Regulatory lifecycle badges */
.reg-inforce  { background: #05966922; color: #34d399; border: 1px solid #05966955; }
.reg-soon     { background: #b4530922; color: #fb923c; border: 1px solid #b4530955; }
.reg-upcoming { background: #1d4ed822; color: #60a5fa; border: 1px solid #1d4ed855; }
.reg-draft    { background: #71717a22; color: #a1a1aa; border: 1px solid #71717a55; }
.reg-unknown  { background: #37415122; color: #94a3b8; border: 1px solid #37415155; }

/* Regulation card */
.reg-card {
    background: #161b27;
    border: 1px solid #1e2535;
    border-radius: 12px;
    padding: 1rem 1.25rem;
    margin-bottom: 0.6rem;
    transition: border-color 0.15s;
}
.reg-card:hover { border-color: #334155; }
.reg-card-title { font-weight: 600; color: #ffffff !important; font-size: 0.9rem; margin-bottom: 0.3rem; }
.reg-card-meta  { font-size: 0.75rem; color: #cbd5e1 !important; }
.reg-card-source { color: #38bdf8 !important; font-weight: 500; }
.reg-card *     { color: #ffffff !important; }
.source-tag {
    display: inline-block;
    background: #0f2744;
    color: #38bdf8 !important;
    border: 1px solid #1e4d7b;
    border-radius: 6px;
    padding: 1px 8px;
    font-size: 0.7rem;
    font-weight: 600;
    margin-right: 6px;
}
</style>
""", unsafe_allow_html=True)


# ── Helpers ──────────────────────────────────────────────────────────────────
def _status_badge(status: str) -> str:
    cls = {"Open": "badge-open", "In Progress": "badge-inprog", "Closed": "badge-closed"}.get(status, "badge-na")
    return f'<span class="badge {cls}">{status or "N/A"}</span>'


def _source_tag(source: str) -> str:
    return f'<span class="source-tag">{source or "—"}</span>' if source else ""


_REG_STATUS_CSS = {
    "In Force":           "reg-inforce",
    "Upcoming ≤1 Month":  "reg-soon",
    "Upcoming ≤3 Months": "reg-soon",
    "Upcoming":           "reg-upcoming",
    "Draft":              "reg-draft",
    "Unknown":            "reg-unknown",
}


def _reg_status(reg) -> tuple[str, str]:
    """
    Compute regulatory lifecycle label + CSS class from force_status + effective_date.
    Returns (label, css_class).
    Separate from compliance status (Open / In Progress / Closed).
    """
    fs = getattr(reg, "force_status", None) or ""
    ed = getattr(reg, "effective_date", None)
    today = date.today()
    if fs == "Draft":
        return "Draft", "reg-draft"
    if fs == "In Force" or (ed and ed <= today):
        return "In Force", "reg-inforce"
    if ed:
        delta = (ed - today).days
        if delta <= 31:
            return "Upcoming ≤1 Month", "reg-soon"
        if delta <= 90:
            return "Upcoming ≤3 Months", "reg-soon"
        return "Upcoming", "reg-upcoming"
    return "Unknown", "reg-unknown"


def _reg_status_badge(label: str) -> str:
    cls = _REG_STATUS_CSS.get(label, "reg-unknown")
    return f'<span class="badge {cls}">{label}</span>'


def _find_similar_regulations(title: str, source: str, s, cutoff: float = 0.75) -> list[dict]:
    """
    Return existing DB regulations whose title is >= cutoff similar to the given title.
    Uses SequenceMatcher for fuzzy comparison.
    """
    norm_new = title.strip().lower()
    existing = s.execute(select(Regulation.id, Regulation.title, Regulation.source)).all()
    matches = []
    for row in existing:
        ratio = SequenceMatcher(None, norm_new, (row.title or "").strip().lower()).ratio()
        if ratio >= cutoff:
            matches.append({
                "id": row.id,
                "title": row.title,
                "source": row.source,
                "ratio": ratio,
            })
    return sorted(matches, key=lambda x: -x["ratio"])


def _extract_pdf_pages(uploaded_file) -> list[str]:
    """
    Extract text from every page of a PDF.
    Returns a list of page text strings (one per page).
    """
    import io
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(uploaded_file.read()))
    pages = []
    for page in reader.pages:
        t = (page.extract_text() or "").strip()
        pages.append(t)   # keep even if empty so page numbers stay aligned
    return pages


def _chunk_pages(pages: list[str], chunk_chars: int = 16000) -> list[str]:
    """
    Group consecutive pages into chunks that stay under chunk_chars.
    Splits at page boundaries so regulations are never cut in half mid-item.
    """
    chunks, current, current_len = [], [], 0
    for page_text in pages:
        page_len = len(page_text)
        if current and current_len + page_len > chunk_chars:
            chunks.append("\n\n".join(current))
            current, current_len = [], 0
        current.append(page_text)
        current_len += page_len
    if current:
        chunks.append("\n\n".join(current))
    return [c for c in chunks if c.strip()]


def _ingest_pdf_regulations(pages: list[str], source_label: str, filename: str) -> dict:
    """
    Chunk the PDF pages and run the AI extraction pipeline on each chunk.
    Combines all results and saves each regulation item to the DB.
    Returns {"created": N, "skipped": N, "chunks": C, "items": [...titles...]}
    """
    from agent import _extract_obligations_with_ai
    from sqlalchemy import and_

    chunks = _chunk_pages(pages, chunk_chars=16000)
    all_obligations = []

    for i, chunk in enumerate(chunks):
        obs = _extract_obligations_with_ai(
            subject=f"{filename} [part {i+1}/{len(chunks)}]",
            body_preview="",
            body_html="",
            attachment_text=chunk,
        )
        all_obligations.extend(obs)

    # Deduplicate across chunks by normalised title
    seen_titles: set[str] = set()
    unique_obligations = []
    for ob in all_obligations:
        key = (ob.get("title") or "").strip().lower()
        if key and key not in seen_titles:
            seen_titles.add(key)
            unique_obligations.append(ob)

    created, skipped = 0, 0
    titles: list[str] = []

    with SessionLocal() as s:
        for ob in unique_obligations:
            title = (ob.get("title") or "").strip()
            if not title:
                continue
            existing = s.execute(
                select(Regulation).where(
                    and_(Regulation.title == title, Regulation.source == source_label)
                )
            ).scalar_one_or_none()
            if existing:
                skipped += 1
                continue
            reg = Regulation(
                title=title,
                source=source_label,
                summary=ob.get("description") or None,
                effective_date=ob.get("due_date") or None,
                category=join_multi(ob.get("departments") or []),
                fleet_tags=join_multi(ob.get("applicable_fleet") or []),
                jurisdiction="Global",
                status="Open",
            )
            s.add(reg)
            s.flush()
            lnk = RegulationLink(
                regulation_id=reg.id,
                url=filename,
                title=filename,
                link_type="pdf",
            )
            s.add(lnk)
            created += 1
            titles.append(title)
        s.commit()

    return {"created": created, "skipped": skipped, "chunks": len(chunks), "items": titles}


FLEET_TYPES = ["Container Vessels", "Bulk Carriers", "Tankers"]


def load_regulations(status_filter=None, source_filter=None, search=None, fleet_filter=None, force_filter=None):
    today = date.today()

    def _matches_force(r) -> bool:
        if not force_filter or force_filter == "All":
            return True
        fs = getattr(r, "force_status", None) or ""
        ed = getattr(r, "effective_date", None)
        if force_filter == "Draft / Unknown":
            return fs == "Draft" or (not ed and fs not in ("In Force",))
        if force_filter == "In Force":
            return fs == "In Force" or (ed and ed <= today)
        if not ed:
            return False
        delta = (ed - today).days
        if force_filter == "≤ 1 Month":
            return 0 < delta <= 31
        if force_filter == "≤ 3 Months":
            return 0 < delta <= 90
        if force_filter == "> 3 Months":
            return delta > 90
        return True

    with SessionLocal() as s:
        regs = s.execute(select(Regulation).order_by(Regulation.received_at.desc())).scalars().all()
        rows = []
        for r in regs:
            if status_filter and status_filter != "All" and r.status != status_filter:
                continue
            if source_filter and source_filter != "All" and r.source != source_filter:
                continue
            if search and search.lower() not in (r.title or "").lower() and search.lower() not in (r.summary or "").lower():
                continue
            if fleet_filter and fleet_filter != "All":
                tags = r.fleet_tags or ""
                if fleet_filter.lower() not in tags.lower():
                    continue
            if not _matches_force(r):
                continue
            _rs_label, _ = _reg_status(r)
            rows.append({
                "ID": r.id,
                "Title": r.title,
                "Source": r.source or "—",
                "Jurisdiction": r.jurisdiction or "—",
                "Department": r.category or "—",
                "Assigned To": getattr(r, "assignee", None) or "—",
                "Effective": str(r.effective_date) if r.effective_date else "—",
                "Status": r.status or "N/A",
                "Reg. Status": _rs_label,
                "Fleet": r.fleet_tags or "—",
                "Summary": (r.summary or "")[:120] + "…" if len(r.summary or "") > 120 else (r.summary or ""),
            })
        return rows


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚓ RegTracker")
    st.caption("Maritime Regulation Monitor")
    st.divider()

    st.markdown("## Filters")
    status_filter = st.selectbox("Status", ["All", "Open", "In Progress", "Closed", "N/A"])
    with SessionLocal() as _s:
        _all_sources = [r for r in _s.execute(select(Regulation.source).distinct()).scalars().all() if r]
    source_filter = st.selectbox("Source", ["All"] + sorted(set(_all_sources)))
    fleet_filter = st.selectbox("Fleet type", ["All"] + FLEET_TYPES)
    force_filter = st.selectbox(
        "Entry into Force",
        ["All", "In Force", "≤ 1 Month", "≤ 3 Months", "> 3 Months", "Draft / Unknown"],
        help="Filter by regulatory lifecycle: whether a regulation is already in force, entering soon, or still a draft.",
    )
    search_term = st.text_input("Search title / summary", placeholder="e.g. MARPOL, EEXI…")

    st.divider()
    st.markdown("## Sources")
    st.caption("🌐 DNV Regulatory News")
    st.caption("🌐 Gard Shipping Changes")
    st.caption("🌐 IMO MediaCentre")
    st.caption("📧 Shared Mailbox")

    st.divider()
    if st.button("Refresh", use_container_width=True):
        st.rerun()

    st.divider()
    st.markdown("## Administration")

    # Re-summarize All — fixes one-sentence summaries from old ingestion prompt
    if st.button("✨ Re-summarize All", use_container_width=True, help="Regenerate rich structured summaries for all regulations that have thin (<200 char) summaries."):
        if not _EMAIL_IMPORTS_OK:
            st.error("OpenAI not available.")
        else:
            with SessionLocal() as _s:
                _stale = [
                    r for r in _s.execute(select(Regulation)).scalars().all()
                    if len(r.summary or "") < 200
                ]
            if not _stale:
                st.success("All summaries are already detailed.")
            else:
                _prog = st.progress(0, text=f"Re-summarizing {len(_stale)} regulation(s)…")
                for _i, _r in enumerate(_stale):
                    _prog.progress((_i + 1) / len(_stale), text=f"Re-summarizing {_i+1}/{len(_stale)}: {_r.title[:60]}…")
                    _new_summary = resummary_with_ai(_r.title, _r.source or "")
                    if _new_summary:
                        with SessionLocal() as _s2:
                            _reg2 = _s2.get(Regulation, _r.id)
                            if _reg2:
                                _reg2.summary = _new_summary
                                _s2.commit()
                _prog.empty()
                st.success(f"✓ Re-summarized {len(_stale)} regulation(s).")
                st.rerun()

    if st.button("🗑 Clear All Regulations", use_container_width=True):
        st.session_state["confirm_clear_db"] = True

    if st.session_state.get("confirm_clear_db"):
        st.warning("⚠️ This will permanently delete ALL regulations, links and email records.")
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("Yes, delete all", type="primary", use_container_width=True):
                with SessionLocal() as _s:
                    from sqlalchemy import text as _sql
                    _s.execute(_sql("DELETE FROM regulation_links"))
                    _s.execute(_sql("DELETE FROM actions"))
                    _s.execute(_sql("DELETE FROM email_ingest"))
                    _s.execute(_sql("DELETE FROM regulations"))
                    _s.commit()
                st.session_state.pop("confirm_clear_db", None)
                st.session_state.pop("selected_reg_id", None)
                st.success("Database cleared.")
                st.rerun()
        with col_no:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop("confirm_clear_db", None)
                st.rerun()


# ── Header ────────────────────────────────────────────────────────────────────
st.markdown("# Maritime Regulation Tracker")
st.caption("Automated monitoring of IMO / ILO / DNV / Gard sources with AI-assisted extraction.")

# ── Metrics ───────────────────────────────────────────────────────────────────
all_rows = load_regulations()
total = len(all_rows)
open_c = sum(1 for r in all_rows if r["Status"] == "Open")
inprog = sum(1 for r in all_rows if r["Status"] == "In Progress")
closed = sum(1 for r in all_rows if r["Status"] == "Closed")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total", total)
c2.metric("Open", open_c)
c3.metric("In Progress", inprog)
c4.metric("Closed", closed)

st.divider()

# ── helpers ───────────────────────────────────────────────────────────────────
def _update_status(reg_id: int, new_status: str):
    with SessionLocal() as s:
        reg = s.get(Regulation, reg_id)
        if reg:
            reg.status = new_status
            s.commit()


def _render_detail_panel(reg_id: int):
    """Full-width detail panel rendered above the list when a regulation is selected."""
    with SessionLocal() as s:
        reg = s.get(Regulation, reg_id)
        if not reg:
            st.session_state.pop("selected_reg_id", None)
            return
        links = s.execute(
            select(RegulationLink).where(RegulationLink.regulation_id == reg.id)
        ).scalars().all()

    # ── Header row ──
    hcol_back, hcol_title = st.columns([1, 8])
    with hcol_back:
        if st.button("← Back", key="detail_back"):
            st.session_state.pop("selected_reg_id", None)
            st.rerun()
    with hcol_title:
        st.markdown(
            f"{_source_tag(reg.source or '')} "
            f"<span style='font-size:1.05rem;font-weight:700;color:#f1f5f9'>{reg.title}</span>",
            unsafe_allow_html=True,
        )

    # Reload reg.assignee fresh for display (it may have just been edited)
    _assignee_display = getattr(reg, "assignee", None) or "—"
    _dept_display = reg.category or "—"

    _rs_label, _rs_cls = _reg_status(reg)
    _instr_display = getattr(reg, "instruments", None) or ""
    _const_display = getattr(reg, "construction_restriction", None) or ""
    _eng_display = getattr(reg, "engine_restriction", None) or ""

    # Instruments formatted as bullet dots
    _instr_html = ""
    if _instr_display:
        _instr_html = f'<div style="margin-top:0.6rem;color:#94a3b8;font-size:0.8rem">📜 <strong style="color:#e2e8f0">Instruments:</strong> {_instr_display.replace(";", " · ")}</div>'
    _const_html = f'<div style="margin-top:0.3rem;color:#94a3b8;font-size:0.8rem">🚢 <strong style="color:#e2e8f0">Construction restriction:</strong> {_const_display}</div>' if _const_display else ""
    _eng_html = f'<div style="margin-top:0.3rem;color:#94a3b8;font-size:0.8rem">⚙️ <strong style="color:#e2e8f0">Engine restriction:</strong> {_eng_display}</div>' if _eng_display else ""

    st.markdown(
        f"""
<div style="background:#161b27;border:1px solid #334155;border-radius:14px;padding:1.4rem 1.6rem;margin:0.5rem 0 1rem;">
  <div style="display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap;margin-bottom:0.6rem;">
    {_status_badge(reg.status)}
    {_reg_status_badge(_rs_label)}
    <span style="color:#94a3b8;font-size:0.82rem">📅 <strong style="color:#e2e8f0">{str(reg.effective_date) if reg.effective_date else '—'}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">🌍 <strong style="color:#e2e8f0">{reg.jurisdiction or '—'}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">🏢 <strong style="color:#e2e8f0">{_dept_display}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">👤 <strong style="color:#e2e8f0">{_assignee_display}</strong></span>
  </div>
  <div style="font-size:0.72rem;color:#64748b;margin-bottom:0.6rem">
    ⓘ Compliance status (left badge) tracks your team's response. Regulatory status (right badge) tracks the regulation's lifecycle.
  </div>
  {_instr_html}{_const_html}{_eng_html}
</div>""",
        unsafe_allow_html=True,
    )

    # ── Edit expander (password-gated) ──
    with st.expander("✏️ Edit Department, Assignee & Regulatory Details", expanded=False):
        if not st.session_state.get("edit_unlocked"):
            _pw_col, _btn_col = st.columns([3, 1])
            with _pw_col:
                _pw_input = st.text_input(
                    "Editor password", type="password",
                    key=f"edit_pw_{reg_id}", label_visibility="collapsed",
                    placeholder="Enter editor password…"
                )
            with _btn_col:
                if st.button("🔓 Unlock", key=f"edit_unlock_{reg_id}"):
                    if _pw_input == EDIT_PASSWORD:
                        st.session_state["edit_unlocked"] = True
                        st.rerun()
                    else:
                        st.error("Incorrect password.")
        else:
            from config import DEPARTMENTS as _DEPTS
            # Current departments as a list
            _cur_depts = [d.strip() for d in (reg.category or "").split(";") if d.strip()]
            _valid_cur_depts = [d for d in _cur_depts if d in _DEPTS]

            _ed1, _ed2 = st.columns(2)
            with _ed1:
                _new_depts = st.multiselect(
                    "Department(s)", options=_DEPTS,
                    default=_valid_cur_depts,
                    key=f"edit_depts_{reg_id}",
                )
            with _ed2:
                _new_assignee = st.text_input(
                    "Assigned To",
                    value=getattr(reg, "assignee", None) or "",
                    key=f"edit_assignee_{reg_id}",
                    placeholder="e.g. J. Smith, M. Lopez",
                    help="Separate multiple names with commas or semicolons",
                )

            _FORCE_OPTIONS = ["Unknown", "Draft", "Upcoming", "In Force"]
            _cur_force = getattr(reg, "force_status", None) or "Unknown"
            _force_idx = _FORCE_OPTIONS.index(_cur_force) if _cur_force in _FORCE_OPTIONS else 0

            _ed3, _ed4 = st.columns(2)
            with _ed3:
                _new_force = st.selectbox(
                    "Regulatory Status",
                    _FORCE_OPTIONS,
                    index=_force_idx,
                    key=f"edit_force_{reg_id}",
                    help="Lifecycle of the regulation itself (distinct from your compliance status)",
                )
            with _ed4:
                _new_instruments = st.text_input(
                    "Instrument references",
                    value=getattr(reg, "instruments", None) or "",
                    key=f"edit_instruments_{reg_id}",
                    placeholder="e.g. MSC.474(101), MEPC.373(80)",
                    help="Comma-separated formal instrument names",
                )

            _ed5, _ed6 = st.columns(2)
            with _ed5:
                _new_const = st.text_input(
                    "Construction restriction",
                    value=getattr(reg, "construction_restriction", None) or "",
                    key=f"edit_const_{reg_id}",
                    placeholder="e.g. vessels built on or after 2024-01-01",
                )
            with _ed6:
                _new_eng = st.text_input(
                    "Engine restriction",
                    value=getattr(reg, "engine_restriction", None) or "",
                    key=f"edit_eng_{reg_id}",
                    placeholder="e.g. diesel engines >130 kW",
                )

            _save_col, _lock_col = st.columns([1, 1])
            with _save_col:
                if st.button("💾 Save", key=f"edit_save_{reg_id}", type="primary"):
                    with SessionLocal() as _es:
                        _ereg = _es.get(Regulation, reg_id)
                        if _ereg:
                            _ereg.category = join_multi(normalize_departments(_new_depts))
                            _ereg.assignee = join_multi(
                                [n.strip() for n in _new_assignee.replace(",", ";").split(";") if n.strip()]
                            )
                            _sf = lambda attr, val: setattr(_ereg, attr, val) if hasattr(_ereg, attr) else None
                            _sf("force_status", _new_force)
                            _sf("instruments", join_multi(
                                [i.strip() for i in _new_instruments.replace(",", ";").split(";") if i.strip()]
                            ) or None)
                            _sf("construction_restriction", _new_const.strip() or None)
                            _sf("engine_restriction", _new_eng.strip() or None)
                            _es.commit()
                    st.success("Saved.")
                    st.rerun()
            with _lock_col:
                if st.button("🔒 Lock", key=f"edit_lock_{reg_id}"):
                    st.session_state["edit_unlocked"] = False
                    st.rerun()

    # ── Body: summary rendered as markdown ──
    st.markdown(reg.summary or "_No summary available._")

    # ── Links ──
    if links:
        st.markdown("---")
        for lnk in links:
            icon = "📄" if lnk.link_type == "pdf" else "🔗"
            if str(lnk.url or "").startswith("http"):
                st.markdown(f"{icon} [{lnk.title or lnk.url}]({lnk.url})")
            else:
                st.markdown(f"📎 {lnk.title or lnk.url}")

    # ── Status + delete + re-summarize actions ──
    st.markdown("---")
    act1, act2, act3, act4, act5 = st.columns(5)
    with act1:
        if st.button("▶ In Progress", key="detail_inprog"):
            _update_status(reg_id, "In Progress")
            st.rerun()
    with act2:
        if st.button("✓ Close", key="detail_closed"):
            _update_status(reg_id, "Closed")
            st.rerun()
    with act3:
        if st.button("↩ Reopen", key="detail_reopen"):
            _update_status(reg_id, "Open")
            st.rerun()
    with act4:
        if st.button("✨ Re-summarize", key="detail_resumm"):
            with st.spinner("Generating rich summary…"):
                try:
                    new_s = resummary_with_ai(reg.title, reg.source or "")
                    if new_s:
                        with SessionLocal() as _s:
                            _r = _s.get(Regulation, reg_id)
                            if _r:
                                _r.summary = new_s
                                _s.commit()
                        st.rerun()
                    else:
                        st.warning("OpenAI unavailable — check OPENAI_API_KEY.")
                except Exception as _ex:
                    st.error(f"Re-summarize failed: {_ex}")
    with act5:
        if st.button("🗑 Delete", key="detail_delete"):
            st.session_state["confirm_delete_id"] = reg_id

    if st.session_state.get("confirm_delete_id") == reg_id:
        st.error("Permanently delete this regulation?")
        dc1, dc2 = st.columns(2)
        with dc1:
            if st.button("Yes, delete", key="confirm_del_yes", type="primary"):
                with SessionLocal() as _s:
                    _reg = _s.get(Regulation, reg_id)
                    if _reg:
                        _s.delete(_reg)
                        _s.commit()
                st.session_state.pop("confirm_delete_id", None)
                st.session_state.pop("selected_reg_id", None)
                st.rerun()
        with dc2:
            if st.button("Cancel", key="confirm_del_no"):
                st.session_state.pop("confirm_delete_id", None)
                st.rerun()

    st.divider()


# ── Regulation list ───────────────────────────────────────────────────────────
st.markdown("## Regulations")

# Show detail panel if a regulation is selected
if "selected_reg_id" in st.session_state:
    _render_detail_panel(st.session_state["selected_reg_id"])

filtered = load_regulations(status_filter, source_filter, search_term, fleet_filter, force_filter)

if not filtered:
    st.info("No regulations match the current filters.")
else:
    view_col, count_col = st.columns([3, 7])
    with view_col:
        view = st.radio("View", ["Table", "Cards"], horizontal=True, label_visibility="collapsed")
    with count_col:
        st.caption(f"{len(filtered)} regulation(s) shown")

    if view == "Table":
        df = pd.DataFrame(filtered)
        display_cols = ["ID", "Title", "Source", "Fleet", "Reg. Status", "Department", "Assigned To", "Effective", "Status"]
        event = st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
            height=420,
            on_select="rerun",
            selection_mode="single-row",
            column_config={
                "ID": st.column_config.NumberColumn("ID", width=50),
                "Title": st.column_config.TextColumn("Title", width=240),
                "Source": st.column_config.TextColumn("Source", width=110),
                "Fleet": st.column_config.TextColumn("Fleet", width=120),
                "Reg. Status": st.column_config.TextColumn("Reg. Status", width=130),
                "Department": st.column_config.TextColumn("Department", width=120),
                "Assigned To": st.column_config.TextColumn("Assigned To", width=130),
                "Effective": st.column_config.TextColumn("Effective", width=95),
                "Status": st.column_config.TextColumn("Status", width=90),
            },
        )
        if event.selection.rows:
            st.session_state["selected_reg_id"] = filtered[event.selection.rows[0]]["ID"]
            st.rerun()

    else:
        # Scrollable card container — fixed height, no page growth
        with st.container(height=620, border=False):
            for row in filtered:
                card_col, btn_col = st.columns([10, 1])
                with card_col:
                    # Fleet tags as small pills
                    fleet_pills = ""
                    if row["Fleet"] and row["Fleet"] != "—":
                        for ft in row["Fleet"].split(";"):
                            ft = ft.strip()
                            if ft:
                                fleet_pills += f'<span style="display:inline-block;background:#0f2d1e;color:#34d399;border:1px solid #065f46;border-radius:5px;padding:1px 7px;font-size:0.68rem;font-weight:600;margin-right:4px">{ft}</span>'
                    _card_assignee = row.get("Assigned To", "—")
                    _assignee_html = (
                        f'&nbsp;·&nbsp;<span>👤 {_card_assignee}</span>'
                        if _card_assignee and _card_assignee != "—" else ""
                    )
                    _card_rs = row.get("Reg. Status", "Unknown")
                    st.markdown(f"""
<div class="reg-card">
  <div class="reg-card-title">{_source_tag(row['Source'])}{row['Title']}</div>
  <div class="reg-card-meta" style="margin:4px 0">
    {_status_badge(row['Status'])} {_reg_status_badge(_card_rs)} &nbsp;
    <span>📅 {row['Effective']}</span> &nbsp;·&nbsp;
    <span>🏢 {row['Department']}</span>{_assignee_html}
  </div>
  <div style="margin:4px 0">{fleet_pills}</div>
  <div style="color:#94a3b8;font-size:0.78rem;margin-top:0.3rem">{row['Summary'][:180]}{'…' if len(row['Summary']) > 180 else ''}</div>
</div>""", unsafe_allow_html=True)
                with btn_col:
                    if st.button("View", key=f"open_{row['ID']}"):
                        st.session_state["selected_reg_id"] = row["ID"]
                        st.rerun()

st.divider()

# ── Website scanner ───────────────────────────────────────────────────────────
st.markdown("## Website Scanner")
st.caption("Scans DNV and Gard for newly published regulatory updates. AI extracts structured data before you confirm.")

_wscan_btn_col, _wscan_cancel_col = st.columns([2, 1])
with _wscan_btn_col:
    _do_scan = st.button("🔍 Scan Regulatory Websites", type="primary", use_container_width=True)
with _wscan_cancel_col:
    if st.session_state.get("pending_web_regs") is not None:
        if st.button("✗ Cancel", use_container_width=True):
            st.session_state.pop("pending_web_regs", None)
            st.rerun()

if _do_scan:
    _raw_previews = []
    _scan_status = st.empty()
    _scan_progress = st.progress(0, text="Discovering articles…")

    try:
        # Phase 1: discover all article URLs
        _scan_status.info("Discovering articles from DNV and Gard…")
        _all_items = discover_articles()
        _total = len(_all_items)
        _scan_status.info(f"Found **{_total}** article(s). Running AI extraction…")

        # Phase 2: download + AI extract each
        from web_ingest import download_article, _extract_web_article_with_ai
        from models import join_multi as _jm

        for _idx, _item in enumerate(_all_items):
            _scan_progress.progress(
                (_idx + 1) / max(_total, 1),
                text=f"AI processing article {_idx + 1} of {_total}…"
            )
            _clean = {k: v for k, v in _item.items() if not k.startswith("_")}

            # Gard structured digest items
            if _clean.get("item_title"):
                _raw_previews.append({
                    "_ob": _clean,
                    "_url": _clean.get("source_url", ""),
                    "_source": _clean.get("publisher") or _clean.get("source_name") or "Gard",
                    "is_skip": False,
                    "title": _clean["item_title"],
                    "due_date": _clean.get("effective_date") or "",
                    "force_status": "Unknown",
                    "fleet": _jm(_clean.get("applicable_fleet") or []) or "—",
                    "dept": _jm(_clean.get("departments") or ["HSEQ"]),
                })
                continue

            # Plain article URL items
            _url = _clean.get("source_url") or _clean.get("url")
            if not _url:
                continue
            _src = _clean.get("publisher") or _clean.get("source") or "Web"
            _atitle, _atext = download_article(_url)
            if not _atitle:
                continue
            _ai = _extract_web_article_with_ai(_atitle, _atext or "", _url, _src)
            _raw_previews.append({
                "_ob": {**_clean, **_ai, "_original_url": _url},
                "_url": _url,
                "_source": _src,
                "is_skip": bool(_ai.get("skip")),
                "title": (_ai.get("title") or _atitle)[:250],
                "due_date": _ai.get("due_date") or "",
                "force_status": _ai.get("force_status") or "Unknown",
                "fleet": _jm(_ai.get("applicable_fleet") or []) or "—",
                "dept": _jm(_ai.get("departments") or ["HSEQ"]),
            })

        _scan_progress.empty()
        _scan_status.empty()

        # Check duplicates
        _regulatory = [p for p in _raw_previews if not p["is_skip"]]
        _skipped_ai = len(_raw_previews) - len(_regulatory)

        with SessionLocal() as _chk_s:
            from sqlalchemy import and_
            for p in _regulatory:
                _ex = _chk_s.execute(
                    select(Regulation).where(
                        and_(Regulation.title == p["title"],
                             Regulation.source == p["_source"])
                    )
                ).scalar_one_or_none()
                p["_warning"] = "Exact duplicate — will skip" if _ex else ""
                p["_include"] = not bool(_ex)

        # Store for review step
        st.session_state["pending_web_regs"] = _regulatory
        st.session_state["web_skipped_ai"] = _skipped_ai
        st.rerun()

    except Exception as _scan_err:
        _scan_progress.empty()
        _scan_status.error(f"Scan failed: {_scan_err}")


# ── Web scan review table ─────────────────────────────────────────────────────
if st.session_state.get("pending_web_regs") is not None:
    _wpending = st.session_state["pending_web_regs"]
    _wskipped = st.session_state.get("web_skipped_ai", 0)

    st.markdown(f"### 🌐 Review Scanned Articles")
    _winfo_parts = [f"**{len(_wpending)} regulatory article(s)** found"]
    if _wskipped:
        _winfo_parts.append(f"**{_wskipped}** non-regulatory article(s) discarded by AI")
    st.caption(" · ".join(_winfo_parts) + ". Uncheck items you don't want to save, then click **Save Selected**.")

    _wdisplay = [{
        "Include":        p["_include"],
        "Title":          p["title"],
        "Source":         p["_source"],
        "Force Status":   p["force_status"],
        "Effective Date": p["due_date"],
        "Fleet":          p["fleet"],
        "Department":     p["dept"],
        "⚠️ Warning":     p["_warning"],
    } for p in _wpending]

    _wedited = st.data_editor(
        pd.DataFrame(_wdisplay),
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Include":        st.column_config.CheckboxColumn("Include", width=70),
            "Title":          st.column_config.TextColumn("Title", width=300),
            "Source":         st.column_config.TextColumn("Source", width=80),
            "Force Status":   st.column_config.SelectboxColumn(
                                  "Force Status", width=120,
                                  options=["Unknown", "Draft", "Upcoming", "In Force"]
                              ),
            "Effective Date": st.column_config.TextColumn("Effective Date", width=110),
            "Fleet":          st.column_config.TextColumn("Fleet", width=130),
            "Department":     st.column_config.TextColumn("Department", width=120),
            "⚠️ Warning":     st.column_config.TextColumn("⚠️ Warning", width=220),
        },
        key="web_review_editor",
    )

    _wsave_col, _wcancel_col = st.columns([1, 1])
    with _wsave_col:
        if st.button("✓ Save Selected", type="primary", use_container_width=True, key="web_save_btn"):
            from sqlalchemy import and_
            from models import join_multi as _jm2
            _wcreated, _wskip2 = 0, 0
            with SessionLocal() as _wss:
                for _widx, _wrow in _wedited.iterrows():
                    if not _wrow.get("Include", False):
                        _wskip2 += 1
                        continue
                    _wt = str(_wrow.get("Title") or "").strip()
                    if not _wt:
                        continue
                    _wsrc = str(_wrow.get("Source") or "Web")
                    _wex = _wss.execute(
                        select(Regulation).where(
                            and_(Regulation.title == _wt, Regulation.source == _wsrc)
                        )
                    ).scalar_one_or_none()
                    if _wex:
                        _wskip2 += 1
                        continue

                    _wob = _wpending[_widx]["_ob"] if _widx < len(_wpending) else {}
                    _weff_raw = str(_wrow.get("Effective Date") or "").strip()
                    _weff = None
                    if _weff_raw:
                        try:
                            from dateutil.parser import parse as _wdtp
                            _weff = _wdtp(_weff_raw).date()
                        except Exception:
                            pass
                    _wfs = str(_wrow.get("Force Status") or "Unknown")

                    _wreg = Regulation(
                        title=_wt,
                        source=_wsrc,
                        summary=_wob.get("description") or None,
                        effective_date=_weff,
                        category=str(_wrow.get("Department") or "HSEQ"),
                        jurisdiction="Global",
                        status="Open",
                    )
                    _safe_set_fn = lambda obj, attr, val: setattr(obj, attr, val) if hasattr(obj, attr) else None
                    _safe_set_fn(_wreg, "fleet_tags",               str(_wrow.get("Fleet") or "") or None)
                    _safe_set_fn(_wreg, "force_status",             _wfs)
                    _safe_set_fn(_wreg, "instruments",              _jm2(_wob.get("instruments") or []) or None)
                    _safe_set_fn(_wreg, "construction_restriction", _wob.get("construction_restriction") or None)
                    _safe_set_fn(_wreg, "engine_restriction",       _wob.get("engine_restriction") or None)

                    _wss.add(_wreg)
                    _wss.flush()

                    _wurl = _wpending[_widx]["_url"] if _widx < len(_wpending) else ""
                    if _wurl:
                        _wss.add(RegulationLink(
                            regulation_id=_wreg.id,
                            url=_wurl,
                            link_type="news",
                            title="Source article",
                        ))
                    _wcreated += 1

                _wss.commit()

            st.success(
                f"✓ **{_wcreated}** regulation(s) saved &nbsp;·&nbsp; "
                f"**{_wskip2}** skipped (unchecked or duplicate)"
            )
            st.session_state.pop("pending_web_regs", None)
            st.session_state.pop("web_skipped_ai", None)
            st.rerun()

    with _wcancel_col:
        if st.button("✗ Cancel", use_container_width=True, key="web_cancel_btn2"):
            st.session_state.pop("pending_web_regs", None)
            st.session_state.pop("web_skipped_ai", None)
            st.rerun()

st.divider()

# ── PDF Upload ────────────────────────────────────────────────────────────────
st.markdown("## PDF Upload")
st.caption("Upload a regulatory digest PDF (Lloyd's Register, DNV, Gard, IMO) — AI will extract every regulation item automatically.")

_up_col, _cfg_col = st.columns([2, 1])

with _up_col:
    uploaded_pdf = st.file_uploader(
        "Drop a PDF here or click to browse",
        type=["pdf"],
        label_visibility="collapsed",
    )

with _cfg_col:
    pdf_source_label = st.text_input(
        "Source label",
        value="Lloyd's Register",
        help="Tag applied to all regulations extracted from this PDF (e.g. Lloyd's Register, DNV, Gard)",
    )

if uploaded_pdf is not None:
    st.markdown(f"**{uploaded_pdf.name}** — {uploaded_pdf.size / 1024:.0f} KB")

    if st.button("Extract Regulations from PDF", type="primary"):
        try:
            with st.spinner("Reading PDF pages…"):
                pages = _extract_pdf_pages(uploaded_pdf)
            total_chars = sum(len(p) for p in pages)
            n_chunks = len(_chunk_pages(pages, chunk_chars=16000))
            st.info(
                f"📄 {len(pages)} pages · {total_chars:,} characters · "
                f"will process in **{n_chunks} chunk(s)**"
            )

            progress = st.progress(0, text="Starting AI extraction…")
            all_obligations = []

            from agent import _extract_obligations_with_ai
            chunks = _chunk_pages(pages, chunk_chars=16000)

            for i, chunk in enumerate(chunks):
                progress.progress(
                    (i + 1) / len(chunks),
                    text=f"Processing chunk {i+1} of {len(chunks)}…"
                )
                obs = _extract_obligations_with_ai(
                    subject=f"{uploaded_pdf.name} [part {i+1}/{len(chunks)}]",
                    body_preview="",
                    body_html="",
                    attachment_text=chunk,
                )
                all_obligations.extend(obs)

            progress.empty()

            # Dedup within PDF by normalised title
            seen_keys: set[str] = set()
            unique_obs = []
            for ob in all_obligations:
                key = (ob.get("title") or "").strip().lower()
                if key and key not in seen_keys:
                    seen_keys.add(key)
                    unique_obs.append(ob)

            if not unique_obs:
                st.warning(
                    "No regulation items were extracted. "
                    "Check that the PDF contains structured regulatory content "
                    "(entry into force dates, MARPOL/SOLAS references, etc.)"
                )
            else:
                # Build review table with duplicate flags
                from sqlalchemy import and_
                _source = pdf_source_label.strip() or "PDF Upload"
                review_rows = []
                with SessionLocal() as _rs:
                    for ob in unique_obs:
                        _t = (ob.get("title") or "").strip()
                        if not _t:
                            continue
                        _exact = _rs.execute(
                            select(Regulation).where(
                                and_(Regulation.title == _t, Regulation.source == _source)
                            )
                        ).scalar_one_or_none()
                        if _exact:
                            _warn = "⚠️ Exact duplicate"
                            _include = False
                        else:
                            _similar = _find_similar_regulations(_t, _source, _rs)
                            if _similar:
                                _best = _similar[0]
                                _pct = int(_best["ratio"] * 100)
                                _warn = f"≈ {_best['title'][:45]}… ({_pct}%)"
                                _include = True
                            else:
                                _warn = ""
                                _include = True
                        _due = ob.get("due_date")
                        _fs = ob.get("force_status") or "Unknown"
                        review_rows.append({
                            "Include": _include,
                            "Title": _t,
                            "Force Status": _fs,
                            "Effective Date": str(_due) if _due else "",
                            "Fleet": join_multi(ob.get("applicable_fleet") or []),
                            "Department": join_multi(ob.get("departments") or []),
                            "⚠️ Warning": _warn,
                            "_ob": ob,   # carry full data for save
                        })

                # Store for save step
                st.session_state["pending_regs"] = review_rows
                st.session_state["pdf_source_label"] = _source
                st.session_state["pdf_filename"] = uploaded_pdf.name
                st.rerun()

        except Exception as _pdf_ex:
            st.error(f"PDF processing failed: {_pdf_ex}")

# ── Review table (shown after extraction, before save) ────────────────────────
if st.session_state.get("pending_regs") is not None:
    _pending = st.session_state["pending_regs"]
    _psource = st.session_state.get("pdf_source_label", "PDF Upload")
    _pfname  = st.session_state.get("pdf_filename", "")

    st.markdown(f"### 📋 Review Extracted Regulations — *{_psource}*")
    st.caption(
        f"**{len(_pending)} item(s)** extracted from **{_pfname}**. "
        "Review below — uncheck any you don't want to save, or correct titles/dates. "
        "Exact duplicates are pre-unchecked. Click **Save Selected** when ready."
    )

    # Build dataframe for editor (drop internal _ob key)
    _display_pending = [
        {k: v for k, v in row.items() if k != "_ob"}
        for row in _pending
    ]
    _edited = st.data_editor(
        pd.DataFrame(_display_pending),
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "Include":        st.column_config.CheckboxColumn("Include", width=70),
            "Title":          st.column_config.TextColumn("Title", width=280),
            "Force Status":   st.column_config.SelectboxColumn(
                                  "Force Status", width=120,
                                  options=["Unknown", "Draft", "Upcoming", "In Force"]
                              ),
            "Effective Date": st.column_config.TextColumn("Effective Date", width=110),
            "Fleet":          st.column_config.TextColumn("Fleet", width=130),
            "Department":     st.column_config.TextColumn("Department", width=130),
            "⚠️ Warning":     st.column_config.TextColumn("⚠️ Warning", width=220),
        },
    )

    _save_col2, _cancel_col = st.columns([1, 1])
    with _save_col2:
        if st.button("✓ Save Selected", type="primary", use_container_width=True):
            from sqlalchemy import and_
            created, skipped = 0, 0
            titles = []
            with SessionLocal() as _ss:
                for idx, edited_row in _edited.iterrows():
                    if not edited_row.get("Include", False):
                        skipped += 1
                        continue
                    _t = str(edited_row.get("Title") or "").strip()
                    if not _t:
                        continue
                    # Re-check exact dup after possible title edit
                    _ex2 = _ss.execute(
                        select(Regulation).where(
                            and_(Regulation.title == _t, Regulation.source == _psource)
                        )
                    ).scalar_one_or_none()
                    if _ex2:
                        skipped += 1
                        continue
                    # Carry original AI data for fields not editable in table
                    _orig_ob = _pending[idx]["_ob"] if idx < len(_pending) else {}
                    _eff_raw = str(edited_row.get("Effective Date") or "").strip()
                    _eff = None
                    if _eff_raw:
                        try:
                            from dateutil.parser import parse as _dtp
                            _eff = _dtp(_eff_raw).date()
                        except Exception:
                            pass
                    _fs = str(edited_row.get("Force Status") or "Unknown")
                    reg = Regulation(
                        title=_t,
                        source=_psource,
                        summary=_orig_ob.get("description") or None,
                        effective_date=_eff,
                        category=join_multi(_orig_ob.get("departments") or []),
                        fleet_tags=join_multi(_orig_ob.get("applicable_fleet") or []),
                        jurisdiction="Global",
                        status="Open",
                    )
                    # Set new columns defensively (models.py may be stale on first deploy)
                    _safe_set = lambda obj, attr, val: setattr(obj, attr, val) if hasattr(obj, attr) else None
                    _safe_set(reg, "force_status", _fs)
                    _safe_set(reg, "instruments", join_multi(_orig_ob.get("instruments") or []) or None)
                    _safe_set(reg, "construction_restriction", _orig_ob.get("construction_restriction") or None)
                    _safe_set(reg, "engine_restriction", _orig_ob.get("engine_restriction") or None)
                    _ss.add(reg)
                    _ss.flush()
                    _ss.add(RegulationLink(
                        regulation_id=reg.id,
                        url=_pfname,
                        title=_pfname,
                        link_type="pdf",
                    ))
                    created += 1
                    titles.append(_t)
                _ss.commit()

            st.success(
                f"✓ **{created}** regulation(s) saved &nbsp;·&nbsp; "
                f"**{skipped}** skipped (unchecked or duplicate)"
            )
            st.session_state.pop("pending_regs", None)
            st.session_state.pop("pdf_source_label", None)
            st.session_state.pop("pdf_filename", None)
            if created:
                st.rerun()

    with _cancel_col:
        if st.button("✗ Cancel", use_container_width=True):
            st.session_state.pop("pending_regs", None)
            st.session_state.pop("pdf_source_label", None)
            st.session_state.pop("pdf_filename", None)
            st.rerun()

st.divider()

# ── Email monitor ─────────────────────────────────────────────────────────────
st.markdown("## Email Monitor")

if not _EMAIL_IMPORTS_OK:
    st.error(f"Email module failed to load: {_EMAIL_IMPORT_ERR}")
else:
    _app_perms = bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID and GRAPH_CLIENT_SECRET)
    _delegated = bool(GRAPH_TENANT_ID and GRAPH_CLIENT_ID)

    # ── Auth status ──
    auth_col, info_col = st.columns([1, 2])

    with auth_col:
        if _app_perms:
            st.success("App credentials configured", icon="🔐")
            auth_mode = "app"
        elif _delegated:
            # Check if we have a cached delegated token
            import os
            _token_cache_path = os.path.join(os.path.dirname(__file__), ".token_cache.json")
            _has_cached = os.path.exists(_token_cache_path)
            if _has_cached:
                st.success("Signed in (delegated)", icon="✅")
                auth_mode = "delegated"
            else:
                st.warning("Not signed in", icon="🔑")
                auth_mode = "none"
                if st.button("Sign in to Outlook", type="primary"):
                    with st.spinner("Starting device login flow…"):
                        try:
                            flow_info = start_device_flow()
                            st.session_state["device_flow"] = flow_info
                        except Exception as ex:
                            st.error(f"Could not start sign-in: {ex}")
        else:
            st.warning("No Graph credentials configured", icon="⚠️")
            auth_mode = "none"
            with st.expander("Setup instructions"):
                st.markdown("""
Add to `.streamlit/secrets.toml`:
```toml
GRAPH_TENANT_ID = "your-tenant-id"
GRAPH_CLIENT_ID = "your-app-client-id"
# For org-wide access (requires admin):
GRAPH_CLIENT_SECRET = "your-secret"
# OR just TENANT_ID + CLIENT_ID for user sign-in (no admin needed)
SHARED_MAILBOX = "regulations@reederei-nord.nl"
```
The app only needs **`Mail.Read` delegated permission** — no admin consent required.
                """)

    with info_col:
        if SHARED_MAILBOX:
            st.caption(f"Shared mailbox: **{SHARED_MAILBOX}**")

        with SessionLocal() as _s:
            _mk = (SHARED_MAILBOX or "").replace("@", "_").replace(".", "_")
            _kv = _s.get(KvStore, f"last_mail_sync_{_mk}") if _mk else None
        if _kv:
            st.caption(f"Last synced: {_kv.value}")
        else:
            st.caption("Never synced.")

    # ── Device flow completion ──
    if "device_flow" in st.session_state:
        flow = st.session_state["device_flow"]
        st.info(
            f"**Step 1 — Open this URL in your browser:**\n\n"
            f"👉 [{flow.get('verification_uri', '')}]({flow.get('verification_uri', '')})\n\n"
            f"**Step 2 — Enter this code:** &nbsp; `{flow.get('user_code', '')}`\n\n"
            f"**Step 3 — Sign in** with your `{GRAPH_MAILBOX if 'GRAPH_MAILBOX' in dir() else 'd.banerjee@...'}`"
            f" Microsoft account, then click the button below.",
            icon="🌐",
        )
        if st.button("✅ I've signed in — complete authentication", type="primary"):
            with st.spinner("Completing sign-in…"):
                try:
                    complete_device_flow(flow)
                    del st.session_state["device_flow"]
                    st.success("✓ Signed in successfully!")

                    # ── Show token for Streamlit secrets persistence ──────────
                    token_str = get_token_cache_string()
                    if token_str:
                        st.warning(
                            "**Important — save your sign-in for future restarts.**\n\n"
                            "Streamlit Cloud wipes its file system on every redeploy. "
                            "To avoid signing in again, copy the value below and add it to "
                            "**Streamlit Cloud → Settings → Secrets** as:\n\n"
                            "```toml\nGRAPH_TOKEN_CACHE = '<paste here>'\n```",
                            icon="💾",
                        )
                        st.code(token_str, language="json")
                    st.rerun()
                except Exception as ex:
                    st.error(f"Sign-in failed: {ex}")

    # ── Sync button ──
    if auth_mode in ("app", "delegated"):
        if st.button("Sync Shared Mailbox", type="primary"):
            with st.spinner(f"Syncing {SHARED_MAILBOX}…"):
                try:
                    result = ingest_shared_mailbox(limit=100)
                    note = result.get("note", "")
                    if note:
                        st.info(note)
                    else:
                        st.success(
                            f"✓ {result['created']} new regulation(s) added, "
                            f"{result['skipped']} already seen."
                        )
                        if result["created"]:
                            st.rerun()
                except Exception as exc:
                    st.error(f"Sync failed: {exc}")

st.divider()

# ── Manual entry ──────────────────────────────────────────────────────────────
st.markdown("## Manual Regulation Entry")

with st.form("manual_reg", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        title = st.text_input("Title *")
        source = st.text_input("Source (e.g. IMO, DNV, Lloyd's Register)")
        jurisdiction = st.text_input("Jurisdiction (e.g. Global, EU, USA)")
        man_assignee = st.text_input(
            "Assigned To",
            placeholder="e.g. J. Smith, M. Lopez",
            help="Person(s) responsible — separate multiple names with commas",
        )
    with col2:
        from config import DEPARTMENTS, REG_STATUS_OPTIONS
        category = st.multiselect("Departments", DEPARTMENTS)
        status = st.selectbox("Status", REG_STATUS_OPTIONS)
        eff_date = st.date_input("Effective Date", value=None)
    summary = st.text_area("Summary / Background", height=100)
    submitted = st.form_submit_button("Create Regulation", type="primary", use_container_width=True)

    if submitted:
        if not title.strip():
            st.error("Title is required.")
        else:
            with SessionLocal() as s:
                reg = Regulation(
                    title=title.strip(),
                    source=source.strip() or None,
                    jurisdiction=jurisdiction.strip() or None,
                    category=join_multi(normalize_departments(category)),
                    effective_date=eff_date,
                    summary=summary.strip() or None,
                    status=status,
                    assignee=join_multi(
                        [n.strip() for n in man_assignee.replace(",", ";").split(";") if n.strip()]
                    ) or None,
                )
                s.add(reg)
                s.commit()
            st.success("Regulation created.")
            st.rerun()
