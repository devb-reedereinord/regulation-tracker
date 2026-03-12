"""
agent.py — Microsoft Graph ingestion worker + notifications
- Ensures Inbox/Regulations subfolder exists
- Reads messages, upserts Regulation/Link, dedups via EmailIngest
- Optional notifications via Graph sendMail
- Attachment support: downloads file attachments to ./attachments and registers links
- Includes a test utility to copy the latest Inbox message into Regulations
"""

from __future__ import annotations

import base64
import json
import os
import re
from typing import List, Dict, Optional

import requests
import msal
from dateutil import parser as dtp
from openai import OpenAI

from config import (
    GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
    GRAPH_MAILBOX, GRAPH_PARENT_FOLDER, GRAPH_TARGET_SUBFOLDER,
    SHARED_MAILBOX,
    NOTIFY_MODE, DEFAULT_NOTIFY,
    DEPT_NOTIFY, KEYWORD_NOTIFY, SENDER_NOTIFY,
    OPENAI_API_KEY, OPENAI_MODEL
)
from models import (
    SessionLocal, Regulation, RegulationLink, Action, EmailIngest, KvStore,
    normalize_departments, join_multi
)

# ── Company profile — used to assess regulatory applicability ────────────────
COMPANY_PROFILE = """
Company: Reederei Nord Group (ship management company, Netherlands)
Fleet managed: Container Vessels, Bulk Carriers, Tankers (oil & chemical)
Operates on behalf of the Oldendorff Family and third-party vessel owners.
Vessels trade internationally on global routes.
Relevant conventions: SOLAS, MARPOL (Annex I, II, IV, V, VI), MLC, STCW, ISM, ISPS, CLC, BWM.
Key internal departments: Marine Ops, Technical, HSEQ, Crewing, Human Resources.
"""

FLEET_TYPES = ["Container Vessels", "Bulk Carriers", "Tankers"]

GRAPH_SCOPE        = ["https://graph.microsoft.com/.default"]
GRAPH_SCOPE_DELEGATED = ["https://graph.microsoft.com/Mail.Read"]
GRAPH_BASE         = "https://graph.microsoft.com/v1.0"
_URL_RE            = re.compile(r'(https?://[^\s)>\]]+)', flags=re.I)

# Path for persisting delegated token cache (next to this file)
_TOKEN_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".token_cache.json")


# ---------------------------------------------------------------------------
# Auth & HTTP — supports both application (client_credentials) and delegated
# (device code flow, user-level, no admin consent required)
# ---------------------------------------------------------------------------

def _load_token_cache() -> msal.SerializableTokenCache:
    """
    Load the MSAL token cache.  Priority:
    1. Local file  (.token_cache.json) — used when running locally
    2. GRAPH_TOKEN_CACHE env var        — set via Streamlit secrets for cloud deployments
       where the file system is wiped on every restart.
    """
    cache = msal.SerializableTokenCache()
    if os.path.exists(_TOKEN_CACHE_PATH):
        with open(_TOKEN_CACHE_PATH, "r") as f:
            cache.deserialize(f.read())
    else:
        # Fallback: Streamlit secrets / environment variable
        env_val = os.environ.get("GRAPH_TOKEN_CACHE", "").strip()
        if env_val:
            cache.deserialize(env_val)
    return cache


def _save_token_cache(cache: msal.SerializableTokenCache):
    if cache.has_state_changed:
        with open(_TOKEN_CACHE_PATH, "w") as f:
            f.write(cache.serialize())


def get_token_cache_string() -> str:
    """
    Return the current serialized token cache as a string.
    Used by the UI to show the value the user should paste into Streamlit secrets
    as GRAPH_TOKEN_CACHE so it survives app restarts.
    """
    if os.path.exists(_TOKEN_CACHE_PATH):
        with open(_TOKEN_CACHE_PATH, "r") as f:
            return f.read().strip()
    return os.environ.get("GRAPH_TOKEN_CACHE", "").strip()


def start_device_flow() -> dict:
    """
    Initiate MSAL device-code flow. Returns a dict with:
    - verification_uri: URL the user must visit
    - user_code: code the user enters at that URL
    Store the returned dict and pass it to complete_device_flow().
    Requires only Mail.Read delegated permission — no admin consent needed.
    """
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID):
        raise RuntimeError("GRAPH_TENANT_ID and GRAPH_CLIENT_ID must be set.")
    cache = _load_token_cache()
    app = msal.PublicClientApplication(
        client_id=GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
        token_cache=cache,
    )
    flow = app.initiate_device_flow(scopes=GRAPH_SCOPE_DELEGATED)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to start device flow: {flow}")
    _save_token_cache(cache)
    return flow


def complete_device_flow(flow: dict):
    """
    Block until the user completes the device-code sign-in, then persist the token.
    """
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID):
        raise RuntimeError("GRAPH_TENANT_ID and GRAPH_CLIENT_ID must be set.")
    cache = _load_token_cache()
    app = msal.PublicClientApplication(
        client_id=GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
        token_cache=cache,
    )
    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        raise RuntimeError(f"Device flow sign-in failed: {result}")
    _save_token_cache(cache)
    return result["access_token"]


def _graph_token() -> str:
    """
    Returns a Graph access token.
    Priority:
    1. Application (client_credentials) if GRAPH_CLIENT_SECRET is set → org-wide, needs admin consent
    2. Delegated (cached user token from device flow) → user-level, no admin consent needed
    """
    # ── Application permissions (admin-consented) ──
    if GRAPH_CLIENT_SECRET:
        missing = [k for k, v in {
            "GRAPH_TENANT_ID": GRAPH_TENANT_ID,
            "GRAPH_CLIENT_ID": GRAPH_CLIENT_ID,
        }.items() if not v]
        if missing:
            raise RuntimeError(f"Missing Graph config keys: {missing}")
        app = msal.ConfidentialClientApplication(
            client_id=GRAPH_CLIENT_ID,
            authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
            client_credential=GRAPH_CLIENT_SECRET,
        )
        result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        tok = result.get("access_token")
        if not tok:
            raise RuntimeError(f"MSAL client_credentials failed: {result}")
        return tok

    # ── Delegated (device flow cached token) ──
    if not (GRAPH_TENANT_ID and GRAPH_CLIENT_ID):
        raise RuntimeError("No Graph credentials configured. Set GRAPH_TENANT_ID + GRAPH_CLIENT_ID.")
    cache = _load_token_cache()
    app = msal.PublicClientApplication(
        client_id=GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
        token_cache=cache,
    )
    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError("No cached sign-in. Use 'Sign in to Outlook' in the UI first.")
    result = app.acquire_token_silent(scopes=GRAPH_SCOPE_DELEGATED, account=accounts[0])
    if not result or "access_token" not in result:
        raise RuntimeError(f"Could not refresh token silently: {result}. Sign in again.")
    _save_token_cache(cache)
    return result["access_token"]


def _graph_get(url: str, params: Optional[Dict] = None) -> Dict:
    tok = _graph_token()

    # HARD STOP: if this triggers, you will NOT hit Graph at all
    if not isinstance(tok, str) or len(tok.strip()) < 20:
        raise RuntimeError(f"Graph token invalid/empty. token_len={len(tok.strip()) if isinstance(tok,str) else 'NA'}")

    headers = {"Authorization": f"Bearer {tok}"}
    r = requests.get(url, headers=headers, params=params or {})
    r.raise_for_status()
    return r.json()


def _graph_post(url: str, payload: Dict) -> Dict:
    tok = _graph_token()
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        data=json.dumps(payload),
    )
    r.raise_for_status()
    return r.json() if r.text else {}


def _mail_root() -> str:
    return f"{GRAPH_BASE}/users/{GRAPH_MAILBOX}"


# ---------------------------------------------------------------------------
# Folder handling
# ---------------------------------------------------------------------------
def _ensure_regulations_folder_id() -> str:
    """
    Return the folder ID of Inbox/Regulations, creating it if needed.
    """
    root = _mail_root()
    q = f"{root}/mailFolders/{GRAPH_PARENT_FOLDER}/childFolders"
    j = _graph_get(
        q,
        params={"$filter": f"displayName eq '{GRAPH_TARGET_SUBFOLDER}'", "$select": "id,displayName", "$top": 1},
    )
    val = j.get("value", [])
    if val:
        return val[0]["id"]
    created = _graph_post(f"{root}/mailFolders/{GRAPH_PARENT_FOLDER}/childFolders", {"displayName": GRAPH_TARGET_SUBFOLDER})
    return created["id"]


# ---------------------------------------------------------------------------
# KvStore & dedup
# ---------------------------------------------------------------------------
def _last_run(s: SessionLocal) -> Optional[str]:
    kv = s.get(KvStore, "last_mail_sync")
    return kv.value if kv else None


def _set_last_run(s: SessionLocal, ts: str):
    kv = s.get(KvStore, "last_mail_sync") or KvStore(key="last_mail_sync")
    kv.value = ts
    s.add(kv)
    s.commit()


def _already_processed(s: SessionLocal, internet_id: str) -> bool:
    if not internet_id:
        return False
    # existence check is cheaper than count(*)
    row = s.execute(
        # SELECT 1 FROM email_ingest WHERE internet_message_id = :id LIMIT 1
        EmailIngest.__table__.select().with_only_columns(EmailIngest.internet_message_id).where(
            EmailIngest.internet_message_id == internet_id
        ).limit(1)
    ).first()
    return bool(row)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------
def _keywords(text: str) -> List[str]:
    keys: List[str] = []
    t = (text or "").lower()
    for k in ["mrv", "marpol", "uscg", "imo", "tier iii", "nox", "eiapp", "environment"]:
        if k in t:
            keys.append(k.upper())
    return keys


def _guess_source(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "imo" in t:
        return "IMO"
    if "uscg" in t:
        return "USCG"
    if "eu" in t or "eur-lex" in t or "commission" in t:
        return "EU"
    return None


def _guess_jurisdiction(text: str) -> Optional[str]:
    t = (text or "").lower()
    if "global" in t or "imo" in t:
        return "Global"
    if "uscg" in t or "usa" in t or "united states" in t:
        return "USA"
    if "eu" in t or "european union" in t:
        return "EU"
    return None


def _collect_links_from_html(html: str) -> List[Dict]:
    return [{"url": m.group(1), "title": None, "link_type": "news"} for m in _URL_RE.finditer(html or "")]


def _extract_json_block(text: str) -> Optional[Dict]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", cleaned)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def _extract_obligations_with_ai(subject: str, body_preview: str, body_html: str, attachment_text: str = "") -> List[Dict]:
    """
    Extract regulatory obligations from an email + attachments using AI.

    When a structured regulatory PDF is attached (e.g. Lloyd's Register 'Future IMO and ILO
    Legislation', Gard, DNV circulars), the attachment_text will contain numbered regulatory
    items with entry into force dates, background, and implications.  The prompt handles both
    plain email instructions and structured regulatory document content.
    """
    if not OPENAI_API_KEY:
        return []

    client = OpenAI(api_key=OPENAI_API_KEY)
    body_text = re.sub(r"<[^>]+>", " ", body_html or "")

    # Detect whether attachment looks like a structured regulatory digest
    _is_regulatory_pdf = bool(attachment_text) and any(
        kw in attachment_text[:2000].lower()
        for kw in ["entry into force", "marpol", "solas", "imo", "ilo", "adopted by", "mepc", "msc.", "regulation"]
    )

    if _is_regulatory_pdf:
        # ── Structured regulatory document mode ─────────────────────────────
        system_msg = (
            "You are a maritime compliance analyst. "
            "You extract individual regulatory items from formal IMO/ILO/Classification Society "
            "regulatory digests (e.g. Lloyd's Register 'Future IMO and ILO Legislation', "
            "Gard shipping changes, DNV regulatory news). "
            "Each item is a separate obligation entry."
        )
        prompt = f"""
You are assessing maritime regulations for the following company:
{COMPANY_PROFILE}

The attached document is a maritime regulatory digest. Extract EVERY individual regulatory item
as a separate obligation. For each item return:

- title: regulation title with reference, e.g.
  "MARPOL Annex VI Reg 14 \u2013 In-use fuel oil sampling points (MEPC.324(75))"

- description: structured markdown summary using this EXACT layout \u2014

    One sentence overview of what changed and why it matters.

    **Key requirements:**
    - Specific obligation 1
    - Specific obligation 2
    - Specific obligation 3
    (Include up to 6 bullets covering every distinct obligation or compliance step)

    **Applies to:** Ship types, sizes (GT/DWT thresholds), new vs existing ships, flag states.

    **Entry into force:** Date and any phase-in details (new vs existing ships if different).

    **Reederei Nord relevance:** One sentence on how this specifically affects Reederei Nord's
    Container Vessels, Bulk Carriers, and/or Tankers and what action is needed.

  Use **bold** for all four section labels exactly as shown.

- due_date: earliest entry into force date as YYYY-MM-DD, or null if not yet determined

- department: internal departments affected \u2014 choose only from
  ["Marine Ops", "Technical", "HSEQ", "Crewing", "Human Resources"]

- applicable_fleet: which of Reederei Nord's fleet types this applies to.
  Choose any subset of: ["Container Vessels", "Bulk Carriers", "Tankers"]
  Use [] only if the regulation genuinely does not apply to any of these types.

Return ONLY valid JSON \u2014 no markdown fences, no text outside the JSON:
{{
  "obligations": [
    {{
      "title": "...",
      "description": "...",
      "due_date": "YYYY-MM-DD or null",
      "department": ["HSEQ", "Technical"],
      "applicable_fleet": ["Tankers", "Bulk Carriers"]
    }}
  ]
}}

Rules:
- Extract EVERY numbered regulation entry \u2014 do not skip any.
- Do not fabricate items. No commentary outside the JSON.

Email subject: {subject}

Regulatory document text (may be truncated at {len(attachment_text)} chars):
{attachment_text[:18000]}
""".strip()

    else:
        # ── Standard email mode ──────────────────────────────────────────────
        system_msg = "You extract maritime compliance obligations and deadlines from emails."
        prompt = f"""
You are assessing maritime regulations for the following company:
{COMPANY_PROFILE}

Extract concrete regulatory obligations from this email.
Return ONLY valid JSON \u2014 no markdown fences, no commentary:
{{
  "obligations": [
    {{
      "title": "short obligation title",
      "description": "markdown: overview sentence, **Key requirements:** bullets, **Applies to:**, **Entry into force:**, **Reederei Nord relevance:**",
      "due_date": "YYYY-MM-DD or null",
      "department": ["Marine Ops", "Technical", "HSEQ", "Crewing", "Human Resources"],
      "applicable_fleet": ["Container Vessels", "Bulk Carriers", "Tankers"]
    }}
  ]
}}

Rules:
- Only capture concrete compliance tasks.
- applicable_fleet: subset of ["Container Vessels", "Bulk Carriers", "Tankers"] that this applies to.
- Return an empty list if there are no obligations.

Email subject: {subject}
Email body preview: {body_preview}
Email body text: {body_text[:8000]}
Attachment text: {(attachment_text or "")[:4000]}
""".strip()

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        parsed = _extract_json_block(raw) or {}
    except Exception as ex:
        print(f"[WARN] OpenAI extraction failed: {ex}")
        return []

    out: List[Dict] = []
    for item in parsed.get("obligations", []):
        if not isinstance(item, dict):
            continue
        title = (item.get("title") or "").strip()
        desc = (item.get("description") or "").strip()
        due = item.get("due_date")
        departments = normalize_departments(item.get("department") or [])
        raw_fleet = item.get("applicable_fleet") or []
        applicable_fleet = [f for f in raw_fleet if f in FLEET_TYPES]

        due_date = None
        if due:
            try:
                due_date = dtp.parse(str(due)).date()
            except Exception:
                due_date = None

        if title:
            out.append({
                "title": title,
                "description": desc,
                "due_date": due_date,
                "departments": departments,
                "applicable_fleet": applicable_fleet,
            })
    return out


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
def _list_attachments(message_id: str) -> List[Dict]:
    """Return metadata for all attachments on a message."""
    root = _mail_root()
    j = _graph_get(f"{root}/messages/{message_id}/attachments", params={"$select": "id,name,contentType,size,@odata.type"})
    return j.get("value", [])


def _get_attachment(message_id: str, attachment_id: str) -> Dict:
    """
    Return the full attachment payload.
    For FileAttachment objects, Graph includes 'contentBytes' (base64) and '@odata.type' == '#microsoft.graph.fileAttachment'.
    """
    root = _mail_root()
    return _graph_get(f"{root}/messages/{message_id}/attachments/{attachment_id}")


def _save_attachment_to_disk(att: Dict, folder: str = "attachments") -> Optional[str]:
    """
    Persist a file attachment to local storage and return its file path.
    Only handles microsoft.graph.fileAttachment; itemAttachment (embedded emails) is skipped.
    """
    otype = att.get("@odata.type", "")
    if "#microsoft.graph.fileAttachment" not in otype:
        return None

    name = att.get("name") or f"attachment_{att.get('id', 'unknown')}"
    content_b64 = att.get("contentBytes")
    if not content_b64:
        return None

    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "wb") as f:
        f.write(base64.b64decode(content_b64))
    return path


def _extract_text_from_attachment(att: Dict, max_chars: int = 12000) -> str:
    """
    Best-effort text extraction for common attachment types.
    Supports: plain text, CSV, JSON, XML and PDF files.
    PDF extraction uses pypdf (installed via requirements.txt).
    """
    otype = att.get("@odata.type", "")
    if "#microsoft.graph.fileAttachment" not in otype:
        return ""

    name = (att.get("name") or "").lower()
    content_type = (att.get("contentType") or "").lower()
    content_b64 = att.get("contentBytes")
    if not content_b64:
        return ""

    raw = base64.b64decode(content_b64)

    # ── PDF ──────────────────────────────────────────────────────────────────
    is_pdf = (
        content_type == "application/pdf"
        or name.endswith(".pdf")
    )
    if is_pdf:
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            pages_text: List[str] = []
            for page in reader.pages:
                t = page.extract_text() or ""
                if t.strip():
                    pages_text.append(t.strip())
            full = "\n\n".join(pages_text)
            return full[:max_chars] if full else ""
        except Exception as ex:
            print(f"[WARN] PDF extraction failed for {att.get('name')}: {ex}")
            return ""

    # ── Plain text formats ────────────────────────────────────────────────────
    text_like = (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml"}
        or name.endswith((".txt", ".csv", ".json", ".xml", ".log", ".md"))
    )
    if not text_like:
        return ""

    try:
        decoded = raw.decode("utf-8", errors="ignore").strip()
        return decoded[:max_chars] if decoded else ""
    except Exception:
        return ""


def _infer_link_type_from_name(name: Optional[str]) -> str:
    n = (name or "").lower()
    if n.endswith(".pdf"):
        return "pdf"
    if n.endswith(".xlsx") or n.endswith(".xls"):
        return "excel"
    if n.endswith(".docx") or n.endswith(".doc"):
        return "doc"
    if n.endswith(".csv"):
        return "csv"
    if n.endswith(".png") or n.endswith(".jpg") or n.endswith(".jpeg"):
        return "image"
    return "file"


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
def _send_notification(reg: Regulation, to_list: List[str], subj: str, sender: str, kw: List[str], links: List[Dict]):
    root = _mail_root()
    if links:
        links_html_items = "".join([
            f'<li><a href="{l.get("url")}">{l.get("title") or l.get("url")}</a></li>'
            if str(l.get("url", "")).startswith("http")
            else f'<li>{l.get("title") or l.get("url")}</li>'
            for l in links
        ])
    else:
        links_html_items = "<li>—</li>"

    content = f"""
        <p>A new regulation item was created:</p>
        <p>
           <b>Title:</b> {subj or '—'}<br/>
           <b>Source:</b> {reg.source or '—'} &nbsp; <b>Jurisdiction:</b> {reg.jurisdiction or '—'}<br/>
           <b>Departments:</b> {reg.category or '—'}<br/>
           <b>Keywords:</b> {', '.join(kw) or '—'}<br/>
           <b>Sender:</b> {sender or '—'}
        </p>
        <p><b>Links:</b></p>
        <ul>{links_html_items}</ul>
    """
    payload = {
        "message": {
            "subject": f"[RegTracker] {subj or 'New item'}",
            "body": {"contentType": "HTML", "content": content},
            "toRecipients": [{"emailAddress": {"address": r}} for r in to_list],
        },
        "saveToSentItems": "true",
    }
    _graph_post(f"{root}/sendMail", payload)


# ---------------------------------------------------------------------------
# Re-summarize an existing regulation using AI
# ---------------------------------------------------------------------------
def resummary_with_ai(title: str, source: str) -> str:
    """
    Generate a rich structured markdown summary for an existing regulation
    based solely on its title and source (no original document needed).
    Returns the markdown string, or empty string if OpenAI is unavailable.
    """
    if not OPENAI_API_KEY:
        return ""

    client = OpenAI(api_key=OPENAI_API_KEY)

    prompt = f"""You are a maritime compliance analyst for Reederei Nord Group,
a professional ship management company that manages Container Vessels, Bulk Carriers, and Tankers.

Generate a detailed structured markdown summary for the following maritime regulation.
You MUST use the exact multi-section format below — do NOT collapse everything into one sentence.

Regulation title: {title}
Source / publisher: {source or 'IMO / Classification Society'}

Required output format (replace bracketed text with real content):

One clear sentence explaining what this regulation changes and why it matters.

**Key requirements:**
- [Specific obligation or compliance step 1]
- [Specific obligation or compliance step 2]
- [Add up to 6 bullets — each a distinct, concrete requirement]

**Applies to:** [Which ship types, minimum GT/DWT thresholds, new ships vs existing ships, flag state scope]

**Entry into force:** [Date. Include phase-in details if different for new vs existing ships.]

**Reederei Nord relevance:** [Which of Reederei Nord's fleet types (Container Vessels / Bulk Carriers / Tankers) are affected and what specific action is required.]

Return ONLY the formatted markdown — no preamble, no code fences, no extra commentary."""

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You produce detailed, multi-section maritime regulatory summaries in markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as ex:
        print(f"[WARN] resummary_with_ai failed for '{title}': {ex}")
        return ""


# ---------------------------------------------------------------------------
# Main ingestion
# ---------------------------------------------------------------------------
def ingest_once(limit: int = 50, dry_run: bool = False) -> dict:
    """
    Pull the latest messages from Inbox/Regulations,
    create Regulation + RegulationLink rows, and (optionally) send notifications.
    """
    root = _mail_root()
    folder_id = _ensure_regulations_folder_id()

    params = {
        "$top": max(1, limit),
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body,internetMessageId",
        "$orderby": "receivedDateTime DESC",
    }
    j = _graph_get(f"{root}/mailFolders/{folder_id}/messages", params=params)
    messages = j.get("value", [])

    created, skipped = 0, 0

    with SessionLocal() as s:
        last_run_ts = _last_run(s)

        # Empty folder? -> return early with a helpful message.
        if not messages:
            return {"created": 0, "skipped": 0, "folder": GRAPH_TARGET_SUBFOLDER, "note": "Folder empty"}

        for m in messages:
            internet_id = m.get("internetMessageId") or ""
            received = dtp.parse(m.get("receivedDateTime"))
            if _already_processed(s, internet_id):
                skipped += 1
                continue
            if last_run_ts and received <= dtp.parse(last_run_ts):
                skipped += 1
                continue

            subj = (m.get("subject") or "").strip()
            body_preview = (m.get("bodyPreview") or "")
            body_html = m.get("body", {}).get("content") or ""
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address") or ""
            msg_id = m.get("id")

            # Extract metadata
            kw = _keywords(f"{subj}\n{body_preview}\n{body_html}")
            src = _guess_source(subj + " " + body_html)
            juris = _guess_jurisdiction(subj + " " + body_html)
            html_links = _collect_links_from_html(body_html)

            # Upsert Regulation
            reg = Regulation(
                title=subj or (body_preview[:120] if body_preview else "Untitled"),
                source=src,
                jurisdiction=juris,
                category="",  # filled by rules below
                effective_date=None,
                summary=body_preview,
                status="Open",
            )
            s.add(reg)
            s.flush()  # assign id

            # Body URL links (from HTML)
            for l in html_links:
                s.add(RegulationLink(
                    regulation_id=reg.id,
                    url=l["url"],
                    link_type=l["link_type"],
                    title=l["title"],
                ))

            # Attachments: list + download file attachments
            attachment_text_parts: List[str] = []
            try:
                atts = _list_attachments(msg_id)
                for meta in atts:
                    full = _get_attachment(msg_id, meta["id"])
                    saved_path = _save_attachment_to_disk(full)  # returns local path or None
                    link_type = _infer_link_type_from_name(meta.get("name"))
                    title = meta.get("name") or "attachment"

                    extracted = _extract_text_from_attachment(full)
                    if extracted:
                        attachment_text_parts.append(f"Attachment: {title}\n{extracted}")

                    if saved_path:
                        s.add(RegulationLink(
                            regulation_id=reg.id,
                            url=saved_path,      # local path for now
                            link_type=link_type,
                            title=title,
                        ))
                    else:
                        # Non-file (e.g., itemAttachment) — still register by name
                        s.add(RegulationLink(
                            regulation_id=reg.id,
                            url=title,
                            link_type="item",
                            title=title,
                        ))
            except Exception as ex:
                # Do not break ingestion due to attachment issues
                print(f"[WARN] Attachment handling failed for message {msg_id}: {ex}")

            attachment_context = "\n\n".join(attachment_text_parts)
            ai_obligations = _extract_obligations_with_ai(subj, body_preview, body_html, attachment_context)

            # Dedup record
            s.add(EmailIngest(
                internet_message_id=internet_id or f"local-{reg.id}",
                regulation_id=reg.id,
                received_at=received,
                folder=GRAPH_TARGET_SUBFOLDER,
                subject=subj,
            ))

            # Department + fleet classification (AI + fallback keyword rules)
            depts: List[str] = []
            fleet_tags_parts: List[str] = []
            for ob in ai_obligations:
                depts.extend(ob.get("departments", []))
                fleet_tags_parts.extend(ob.get("applicable_fleet", []))
            if any(k in kw for k in ["MARPOL", "EIAPP", "NOX", "TIER III"]):
                depts.extend(["HSEQ", "Technical"])
            if "USCG" in kw:
                depts.append("Marine Ops")
            if "MRV" in kw:
                depts.append("HSEQ")
            reg.category = join_multi(normalize_departments(depts))
            reg.fleet_tags = join_multi([f for f in fleet_tags_parts if f in FLEET_TYPES])

            for ob in ai_obligations:
                s.add(Action(
                    regulation_id=reg.id,
                    title=ob["title"],
                    description=ob.get("description") or "",
                    due_date=ob.get("due_date"),
                    assignee="",
                    status="Planned",
                ))

            s.add(reg)
            s.commit()
            created += 1

            # Notifications
            if not dry_run and NOTIFY_MODE == "email":
                recipients = set()
                for d in normalize_departments(depts):
                    recipients.update(DEPT_NOTIFY.get(d, []))
                for k in kw:
                    recipients.update(KEYWORD_NOTIFY.get(k, []))
                recipients.update(SENDER_NOTIFY.get(sender.lower(), []))

                if not recipients:
                    recipients.update(DEFAULT_NOTIFY)

                _send_notification(reg, list(recipients), subj, sender, kw, html_links)

        # Bump last_run if we actually scanned messages
        newest_ts = messages[0].get("receivedDateTime")
        _set_last_run(s, newest_ts)

    return {"created": created, "skipped": skipped, "folder": GRAPH_TARGET_SUBFOLDER}


# ---------------------------------------------------------------------------
# Shared mailbox ingestion
# ---------------------------------------------------------------------------
def ingest_shared_mailbox(mailbox: str = None, limit: int = 100, dry_run: bool = False) -> dict:
    """
    Pull all messages from the full inbox of a shared mailbox (e.g. regulations@reederei-nord.nl).
    Uses the same Graph app credentials but targets the shared mailbox address.

    Deduplication is keyed per-mailbox so it doesn't interfere with ingest_once().
    """
    mailbox = mailbox or SHARED_MAILBOX
    if not mailbox:
        return {"created": 0, "skipped": 0, "folder": "inbox", "note": "No shared mailbox configured"}

    mail_root = f"{GRAPH_BASE}/users/{mailbox}"
    sync_key = f"last_mail_sync_{mailbox.replace('@', '_').replace('.', '_')}"

    params = {
        "$top": max(1, limit),
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body,internetMessageId",
        "$orderby": "receivedDateTime DESC",
    }

    try:
        j = _graph_get(f"{mail_root}/mailFolders/inbox/messages", params=params)
    except Exception as exc:
        return {"created": 0, "skipped": 0, "folder": "inbox", "note": f"Graph error: {exc}"}

    messages = j.get("value", [])

    created, skipped = 0, 0

    with SessionLocal() as s:
        # Use per-mailbox sync key so dedup doesn't collide with personal mailbox
        kv_last = s.get(KvStore, sync_key)
        last_run_ts = kv_last.value if kv_last else None

        if not messages:
            return {"created": 0, "skipped": 0, "folder": "inbox", "note": "Inbox empty"}

        for m in messages:
            internet_id = m.get("internetMessageId") or ""
            received = dtp.parse(m.get("receivedDateTime"))

            if _already_processed(s, internet_id):
                skipped += 1
                continue
            if last_run_ts and received <= dtp.parse(last_run_ts):
                skipped += 1
                continue

            subj = (m.get("subject") or "").strip()
            body_preview = (m.get("bodyPreview") or "")
            body_html = m.get("body", {}).get("content") or ""
            sender = ((m.get("from") or {}).get("emailAddress") or {}).get("address") or ""
            msg_id = m.get("id")

            kw = _keywords(f"{subj}\n{body_preview}\n{body_html}")
            src = _guess_source(subj + " " + body_html) or "Shared Mailbox"
            juris = _guess_jurisdiction(subj + " " + body_html)
            html_links = _collect_links_from_html(body_html)

            reg = Regulation(
                title=subj or (body_preview[:120] if body_preview else "Untitled"),
                source=src,
                jurisdiction=juris,
                category="",
                effective_date=None,
                summary=body_preview,
                status="Open",
            )
            s.add(reg)
            s.flush()

            for lnk in html_links:
                s.add(RegulationLink(
                    regulation_id=reg.id,
                    url=lnk["url"],
                    link_type=lnk["link_type"],
                    title=lnk["title"],
                ))

            attachment_text_parts: List[str] = []
            try:
                atts = _list_attachments(msg_id)
                for meta in atts:
                    # Use mail_root for shared mailbox attachment fetching
                    att_url = f"{mail_root}/messages/{msg_id}/attachments/{meta['id']}"
                    full = _graph_get(att_url)
                    saved_path = _save_attachment_to_disk(full)
                    link_type = _infer_link_type_from_name(meta.get("name"))
                    title = meta.get("name") or "attachment"

                    extracted = _extract_text_from_attachment(full)
                    if extracted:
                        attachment_text_parts.append(f"Attachment: {title}\n{extracted}")

                    if saved_path:
                        s.add(RegulationLink(
                            regulation_id=reg.id,
                            url=saved_path,
                            link_type=link_type,
                            title=title,
                        ))
                    else:
                        s.add(RegulationLink(
                            regulation_id=reg.id,
                            url=title,
                            link_type="item",
                            title=title,
                        ))
            except Exception as ex:
                print(f"[WARN] Attachment handling failed for shared mailbox message {msg_id}: {ex}")

            attachment_context = "\n\n".join(attachment_text_parts)
            ai_obligations = _extract_obligations_with_ai(subj, body_preview, body_html, attachment_context)

            s.add(EmailIngest(
                internet_message_id=internet_id or f"shared-{reg.id}",
                regulation_id=reg.id,
                received_at=received,
                folder=f"inbox ({mailbox})",
                subject=subj,
            ))

            depts: List[str] = []
            fleet_tags_parts: List[str] = []
            for ob in ai_obligations:
                depts.extend(ob.get("departments", []))
                fleet_tags_parts.extend(ob.get("applicable_fleet", []))
            if any(k in kw for k in ["MARPOL", "EIAPP", "NOX", "TIER III"]):
                depts.extend(["HSEQ", "Technical"])
            if "USCG" in kw:
                depts.append("Marine Ops")
            if "MRV" in kw:
                depts.append("HSEQ")
            reg.category = join_multi(normalize_departments(depts))
            reg.fleet_tags = join_multi([f for f in fleet_tags_parts if f in FLEET_TYPES])

            for ob in ai_obligations:
                s.add(Action(
                    regulation_id=reg.id,
                    title=ob["title"],
                    description=ob.get("description") or "",
                    due_date=ob.get("due_date"),
                    assignee="",
                    status="Planned",
                ))

            s.add(reg)
            s.commit()
            created += 1

            if not dry_run and NOTIFY_MODE == "email":
                recipients = set()
                for d in normalize_departments(depts):
                    recipients.update(DEPT_NOTIFY.get(d, []))
                for k in kw:
                    recipients.update(KEYWORD_NOTIFY.get(k, []))
                recipients.update(SENDER_NOTIFY.get(sender.lower(), []))
                if not recipients:
                    recipients.update(DEFAULT_NOTIFY)
                _send_notification(reg, list(recipients), subj, sender, kw, html_links)

        # Bump last_run for this mailbox
        newest_ts = messages[0].get("receivedDateTime")
        kv = s.get(KvStore, sync_key) or KvStore(key=sync_key)
        kv.value = newest_ts
        s.add(kv)
        s.commit()

    return {"created": created, "skipped": skipped, "folder": f"inbox ({mailbox})"}


# ---------------------------------------------------------------------------
# Test utility
# ---------------------------------------------------------------------------
def copy_last_inbox_message_to_regulations() -> str:
    """
    Copy the most recent Inbox message into Inbox/Regulations to create a test item.
    Safe server-side copy (no external email is sent).
    """
    root = _mail_root()
    j = _graph_get(f"{root}/mailFolders/inbox/messages", params={"$top": 1, "$select": "id"})
    val = j.get("value", [])
    if not val:
        return "No messages in Inbox to copy."
    mid = val[0]["id"]
    dest_id = _ensure_regulations_folder_id()
    _graph_post(f"{root}/messages/{mid}/copy", {"destinationId": dest_id})
    return "Copied last Inbox message to Inbox/Regulations."


# ---------------------------------------------------------------------------
# CLI entrypoint for scheduled runs
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example: python agent.py
    stats = ingest_once(limit=50, dry_run=False)
    print(f"Ingested: {stats}")
