import streamlit as st
import pandas as pd
from sqlalchemy import select
from datetime import datetime

from models import SessionLocal, Regulation, RegulationLink, KvStore

from web_monitor import discover_articles
from web_ingest import ingest_web_article

try:
    from agent import ingest_shared_mailbox, start_device_flow, complete_device_flow
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

/* Page background */
.stApp { background: #0f1117; color: #e2e8f0; }

/* Sidebar */
[data-testid="stSidebar"] {
    background: #161b27;
    border-right: 1px solid #1e2535;
}
[data-testid="stSidebar"] .stMarkdown h2 {
    color: #60a5fa;
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
[data-testid="metric-container"] label { color: #94a3b8 !important; font-size: 0.75rem; letter-spacing: 0.05em; text-transform: uppercase; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { color: #f1f5f9; font-size: 2rem; font-weight: 700; }

/* Section headers */
h1 { color: #f1f5f9 !important; font-size: 1.6rem !important; font-weight: 700 !important; }
h2 { color: #cbd5e1 !important; font-size: 1.15rem !important; font-weight: 600 !important; border-bottom: 1px solid #1e2535; padding-bottom: 0.4rem; }
h3 { color: #94a3b8 !important; font-size: 0.9rem !important; font-weight: 600 !important; }

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
.reg-card-title { font-weight: 600; color: #e2e8f0; font-size: 0.9rem; margin-bottom: 0.3rem; }
.reg-card-meta  { font-size: 0.75rem; color: #64748b; }
.reg-card-source { color: #38bdf8; font-weight: 500; }
.source-tag {
    display: inline-block;
    background: #0f2744;
    color: #38bdf8;
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


def load_regulations(status_filter=None, source_filter=None, search=None):
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
            rows.append({
                "ID": r.id,
                "Title": r.title,
                "Source": r.source or "—",
                "Jurisdiction": r.jurisdiction or "—",
                "Department": r.category or "—",
                "Effective": str(r.effective_date) if r.effective_date else "—",
                "Status": r.status or "N/A",
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

# ── Regulation list ───────────────────────────────────────────────────────────
st.markdown("## Regulations")

filtered = load_regulations(status_filter, source_filter, search_term)

if not filtered:
    st.info("No regulations match the current filters.")
else:
    # Toggle between card view and table view
    view = st.radio("View", ["Table", "Cards"], horizontal=True, label_visibility="collapsed")

    if view == "Table":
        df = pd.DataFrame(filtered)
        st.dataframe(df, use_container_width=True, hide_index=True, height=420)
    else:
        for row in filtered[:50]:
            st.markdown(f"""
<div class="reg-card">
  <div class="reg-card-title">{_source_tag(row['Source'])}{row['Title']}</div>
  <div class="reg-card-meta">
    {_status_badge(row['Status'])} &nbsp;
    <span>📅 {row['Effective']}</span> &nbsp;·&nbsp;
    <span>🌍 {row['Jurisdiction']}</span> &nbsp;·&nbsp;
    <span>🏢 {row['Department']}</span>
  </div>
  <div style="color:#94a3b8;font-size:0.8rem;margin-top:0.4rem;">{row['Summary']}</div>
</div>""", unsafe_allow_html=True)
        if len(filtered) > 50:
            st.caption(f"Showing 50 of {len(filtered)}. Use filters to narrow down.")

st.divider()

# ── Regulation detail ─────────────────────────────────────────────────────────
st.markdown("## Regulation Detail")

selected_id = st.number_input("Regulation ID", min_value=1, step=1, label_visibility="collapsed",
                               placeholder="Enter regulation ID…")

if st.button("Load Regulation"):
    with SessionLocal() as s:
        reg = s.get(Regulation, int(selected_id))
        if not reg:
            st.error("Regulation not found.")
        else:
            col_l, col_r = st.columns([2, 1])
            with col_l:
                st.markdown(f"### {reg.title}")
                st.markdown(reg.summary or "_No summary._")
            with col_r:
                st.markdown(f"""
<div style="background:#161b27;border:1px solid #1e2535;border-radius:10px;padding:1rem;">
<div style="font-size:0.75rem;color:#64748b;margin-bottom:0.5rem;">DETAILS</div>
<div style="margin:4px 0"><span style="color:#64748b">Source</span> &nbsp; <strong style="color:#38bdf8">{reg.source or '—'}</strong></div>
<div style="margin:4px 0"><span style="color:#64748b">Jurisdiction</span> &nbsp; {reg.jurisdiction or '—'}</div>
<div style="margin:4px 0"><span style="color:#64748b">Department</span> &nbsp; {reg.category or '—'}</div>
<div style="margin:4px 0"><span style="color:#64748b">Effective</span> &nbsp; {str(reg.effective_date) if reg.effective_date else '—'}</div>
<div style="margin:8px 0 0">{_status_badge(reg.status)}</div>
</div>""", unsafe_allow_html=True)

            links = s.execute(
                select(RegulationLink).where(RegulationLink.regulation_id == reg.id)
            ).scalars().all()
            if links:
                st.markdown("**Links**")
                for lnk in links:
                    icon = "📄" if lnk.link_type == "pdf" else "🔗"
                    if str(lnk.url or "").startswith("http"):
                        st.markdown(f"{icon} [{lnk.title or lnk.url}]({lnk.url})")
                    else:
                        st.markdown(f"📎 {lnk.title or lnk.url}")

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
            f"**Open this URL in your browser:** {flow.get('verification_uri', '')}\n\n"
            f"**Enter code:** `{flow.get('user_code', '')}`",
            icon="🌐",
        )
        if st.button("I've signed in — complete authentication"):
            with st.spinner("Completing sign-in…"):
                try:
                    complete_device_flow(flow)
                    del st.session_state["device_flow"]
                    st.success("Signed in successfully!")
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
                from models import join_multi, normalize_departments
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
