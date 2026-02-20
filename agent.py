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
    NOTIFY_MODE, DEFAULT_NOTIFY,
    DEPT_NOTIFY, KEYWORD_NOTIFY, SENDER_NOTIFY,
    OPENAI_API_KEY, OPENAI_MODEL
)
from models import (
    SessionLocal, Regulation, RegulationLink, Action, EmailIngest, KvStore,
    normalize_departments, join_multi
)

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE  = "https://graph.microsoft.com/v1.0"
_URL_RE     = re.compile(r'(https?://[^\s)>\]]+)', flags=re.I)


# ---------------------------------------------------------------------------
# Auth & HTTP
# ---------------------------------------------------------------------------
def _graph_token() -> str:
    if not GRAPH_CLIENT_ID or not GRAPH_CLIENT_SECRET or not GRAPH_TENANT_ID:
        raise RuntimeError(
            "Missing Graph config. Ensure GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET are set "
            "in Streamlit secrets or environment variables."
        )

    app = msal.ConfidentialClientApplication(
        client_id=GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
        client_credential=GRAPH_CLIENT_SECRET
    )

    result = app.acquire_token_silent(GRAPH_SCOPE, account=None) or app.acquire_token_for_client(scopes=GRAPH_SCOPE)

    tok = result.get("access_token")
    if not tok:
        # This prints the real reason from MSAL (invalid client secret, missing consent, etc.)
        raise RuntimeError(f"Graph auth failed (no token). MSAL response: {result}")

    return tok


def _graph_get(url: str, params: Optional[Dict] = None) -> Dict:
    tok = _graph_token()
    if not tok.strip():
        raise RuntimeError("Graph token is empty after auth.")
    r = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, params=params or {})
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
    if not OPENAI_API_KEY:
        return []

    client = OpenAI(api_key=OPENAI_API_KEY)
    body_text = re.sub(r"<[^>]+>", " ", body_html or "")

    prompt = f"""
You are extracting maritime regulatory obligations from an email.
Return ONLY JSON in this exact schema:
{{
  "obligations": [
    {{
      "title": "short obligation title",
      "description": "one or two sentences",
      "due_date": "YYYY-MM-DD or null",
      "department": ["Marine Ops", "Technical", "HSEQ", "Crewing", "Human Resourses"]
    }}
  ]
}}

Rules:
- Capture concrete obligations/compliance tasks and deadlines.
- If there is no obligation, return an empty list.
- Do not include commentary outside JSON.

Email subject:
{subject}

Email body preview:
{body_preview}

Email body text:
{body_text[:10000]}

Attachment text (may be partial):
{(attachment_text or "")[:6000]}
""".strip()

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "You extract compliance obligations and deadlines."},
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


def _extract_text_from_attachment(att: Dict, max_chars: int = 4000) -> str:
    """Best-effort text extraction for common text attachments."""
    otype = att.get("@odata.type", "")
    if "#microsoft.graph.fileAttachment" not in otype:
        return ""

    name = (att.get("name") or "").lower()
    content_type = (att.get("contentType") or "").lower()
    content_b64 = att.get("contentBytes")
    if not content_b64:
        return ""

    text_like = (
        content_type.startswith("text/")
        or content_type in {"application/json", "application/xml"}
        or name.endswith((".txt", ".csv", ".json", ".xml", ".log", ".md"))
    )
    if not text_like:
        return ""

    try:
        raw = base64.b64decode(content_b64)
        decoded = raw.decode("utf-8", errors="ignore").strip()
        if not decoded:
            return ""
        return decoded[:max_chars]
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

            # Department classification (AI + fallback keyword rules)
            depts: List[str] = []
            for ob in ai_obligations:
                depts.extend(ob.get("departments", []))
            if any(k in kw for k in ["MARPOL", "EIAPP", "NOX", "TIER III"]):
                depts.extend(["HSEQ", "Technical"])
            if "USCG" in kw:
                depts.append("Marine Ops")
            if "MRV" in kw:
                depts.append("HSEQ")
            reg.category = join_multi(normalize_departments(depts))

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
