import streamlit as st
import pandas as pd
from sqlalchemy import select
from datetime import datetime

from models import SessionLocal, Regulation, RegulationLink, KvStore, normalize_departments, join_multi

from web_monitor import discover_articles
from web_ingest import ingest_web_article

try:
    from agent import ingest_shared_mailbox, start_device_flow, complete_device_flow, get_token_cache_string
    from config import SHARED_MAILBOX, GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    _EMAIL_IMPORTS_OK = True
    _EMAIL_IMPORT_ERR = ""
except Exception as _e:
    _EMAIL_IMPORTS_OK = False
    _EMAIL_IMPORT_ERR = str(_e)
    SHARED_MAILBOX = ""
    GRAPH_TENANT_ID = GRAPH_CLIENT_ID = GRAPH_CLIENT_SECRET = ""

# ── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RegTracker",
    page_icon="⚓",
    layout="wide",
    initial_sidebar_state="expanded",
)

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


def load_regulations(status_filter=None, source_filter=None, search=None, fleet_filter=None):
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
            rows.append({
                "ID": r.id,
                "Title": r.title,
                "Source": r.source or "—",
                "Jurisdiction": r.jurisdiction or "—",
                "Department": r.category or "—",
                "Effective": str(r.effective_date) if r.effective_date else "—",
                "Status": r.status or "N/A",
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

    st.markdown(
        f"""
<div style="background:#161b27;border:1px solid #334155;border-radius:14px;padding:1.4rem 1.6rem;margin:0.5rem 0 1rem;">
  <div style="display:flex;gap:1.2rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem;">
    {_status_badge(reg.status)}
    <span style="color:#94a3b8;font-size:0.82rem">📅 <strong style="color:#e2e8f0">{str(reg.effective_date) if reg.effective_date else '—'}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">🌍 <strong style="color:#e2e8f0">{reg.jurisdiction or '—'}</strong></span>
    <span style="color:#94a3b8;font-size:0.82rem">🏢 <strong style="color:#e2e8f0">{reg.category or '—'}</strong></span>
  </div>
</div>""",
        unsafe_allow_html=True,
    )

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

    # ── Status + delete actions ──
    st.markdown("---")
    act1, act2, act3, act4, _ = st.columns([1, 1, 1, 1, 2])
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

filtered = load_regulations(status_filter, source_filter, search_term, fleet_filter)

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
        display_cols = ["ID", "Title", "Source", "Fleet", "Department", "Effective", "Status"]
        event = st.dataframe(
            df[display_cols],
            use_container_width=True,
            hide_index=True,
            height=420,
            on_select="rerun",
            selection_mode="single-row",
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
                    st.markdown(f"""
<div class="reg-card">
  <div class="reg-card-title">{_source_tag(row['Source'])}{row['Title']}</div>
  <div class="reg-card-meta" style="margin:4px 0">
    {_status_badge(row['Status'])} &nbsp;
    <span>📅 {row['Effective']}</span> &nbsp;·&nbsp;
    <span>🏢 {row['Department']}</span>
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
st.caption("Scans DNV, Gard, and IMO for newly published regulatory updates.")

if st.button("Scan Regulatory Websites", type="primary"):
    with st.spinner("Scanning sources…"):
        items = discover_articles()
        new_items = 0
        gard_debug = None
        for item in items:
            if item.get("_debug_headings") and gard_debug is None:
                gard_debug = item["_debug_headings"]
            if ingest_web_article(item):
                new_items += 1

    st.success(f"✓ {new_items} new regulatory update(s) discovered.")
    if gard_debug is not None and new_items == 0:
        with st.expander("GARD page headings (diagnosis)"):
            st.write(gard_debug or "(none found — page may be JavaScript-rendered)")

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

            progress.progress(1.0, text="Saving to database…")

            # Dedup across chunks then save
            from sqlalchemy import and_
            seen: set[str] = set()
            unique_obs = []
            for ob in all_obligations:
                key = (ob.get("title") or "").strip().lower()
                if key and key not in seen:
                    seen.add(key)
                    unique_obs.append(ob)

            created, skipped, titles = 0, 0, []
            with SessionLocal() as s:
                for ob in unique_obs:
                    title = (ob.get("title") or "").strip()
                    if not title:
                        continue
                    existing = s.execute(
                        select(Regulation).where(
                            and_(
                                Regulation.title == title,
                                Regulation.source == (pdf_source_label.strip() or "PDF Upload"),
                            )
                        )
                    ).scalar_one_or_none()
                    if existing:
                        skipped += 1
                        continue
                    reg = Regulation(
                        title=title,
                        source=pdf_source_label.strip() or "PDF Upload",
                        summary=ob.get("description") or None,
                        effective_date=ob.get("due_date") or None,
                        category=join_multi(ob.get("departments") or []),
                        fleet_tags=join_multi(ob.get("applicable_fleet") or []),
                        jurisdiction="Global",
                        status="Open",
                    )
                    s.add(reg)
                    s.flush()
                    s.add(RegulationLink(
                        regulation_id=reg.id,
                        url=uploaded_pdf.name,
                        title=uploaded_pdf.name,
                        link_type="pdf",
                    ))
                    created += 1
                    titles.append(title)
                s.commit()

            progress.empty()

            if created == 0 and skipped == 0:
                st.warning(
                    "No regulation items were extracted. "
                    "Check that the PDF contains structured regulatory content "
                    "(entry into force dates, MARPOL/SOLAS references, etc.)"
                )
            else:
                st.success(
                    f"✓ **{created}** regulation(s) added &nbsp;·&nbsp; "
                    f"**{skipped}** already existed &nbsp;·&nbsp; "
                    f"**{n_chunks}** chunks processed"
                )
                if titles:
                    with st.expander(f"View {len(titles)} extracted regulation(s)"):
                        for i, t in enumerate(titles, 1):
                            st.markdown(f"{i}. {t}")
                if created:
                    st.rerun()

        except Exception as _pdf_ex:
            st.error(f"PDF processing failed: {_pdf_ex}")

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
                )
                s.add(reg)
                s.commit()
            st.success("Regulation created.")
            st.rerun()
