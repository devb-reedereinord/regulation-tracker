"""
agent.py — Microsoft Graph ingestion worker + notifications
- Ensures Inbox/Regulations subfolder exists
- Reads messages, upserts Regulation/Link, dedups via EmailIngest
- Optional notifications via Graph sendMail
- Includes a test utility to copy the latest Inbox message into Regulations
"""

import json
import re
from typing import List, Dict
from dateutil import parser as dtp

import requests
import msal

from config import (
    GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
    GRAPH_MAILBOX, GRAPH_PARENT_FOLDER, GRAPH_TARGET_SUBFOLDER,
    NOTIFY_MODE, DEFAULT_NOTIFY,
    DEPT_NOTIFY, KEYWORD_NOTIFY, SENDER_NOTIFY
)
from models import (
    SessionLocal, Regulation, RegulationLink, EmailIngest, KvStore,
    normalize_departments, join_multi, split_multi
)

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE  = "https://graph.microsoft.com/v1.0"
_URL_RE     = re.compile(r'(https?://[^\s)>\]]+)', flags=re.I)

# ---------- Auth & HTTP ----------
def _graph_token() -> str:
    app = msal.ConfidentialClientApplication(
        client_id=GRAPH_CLIENT_ID,
        authority=f"https://login.microsoftonline.com/{GRAPH_TENANT_ID}",
        client_credential=GRAPH_CLIENT_SECRET
    )
    result = app.acquire_token_silent(GRAPH_SCOPE, account=None) or app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    if "access_token" not in result:
        raise RuntimeError(f"Graph auth failed: {result}")
    return result["access_token"]

def _graph_get(url: str, params: Dict=None) -> Dict:
    tok = _graph_token()
    r = requests.get(url, headers={"Authorization": f"Bearer {tok}"}, params=params or {})
    r.raise_for_status()
    return r.json()

def _graph_post(url: str, payload: Dict) -> Dict:
    tok = _graph_token()
    r = requests.post(url,
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
        data=json.dumps(payload))
    r.raise_for_status()
    return r.json() if r.text else {}

def _mail_root() -> str:
    return f"{GRAPH_BASE}/users/{GRAPH_MAILBOX}"

# ---------- Folder handling ----------
def _ensure_regulations_folder_id() -> str:
    """
    Return the folder ID of Inbox/Regulations, creating it if needed.
    """
    root = _mail_root()
    q = f"{root}/mailFolders/{GRAPH_PARENT_FOLDER}/childFolders"
    j = _graph_get(q, params={"$filter": f"displayName eq '{GRAPH_TARGET_SUBFOLDER}'", "$select": "id,displayName", "$top": 1})
    val = j.get("value", [])
    if val:
        return val[0]["id"]
    created = _graph_post(f"{root}/mailFolders/{GRAPH_PARENT_FOLDER}/childFolders", {"displayName": GRAPH_TARGET_SUBFOLDER})
    return created["id"]

# ---------- KvStore & dedup ----------
def _last_run(s: SessionLocal) -> str | None:
    kv = s.get(KvStore, "last_mail_sync")
    return kv.value if kv else None

def _set_last_run(s: SessionLocal, ts: str):
    kv = s.get(KvStore, "last_mail_sync") or KvStore(key="last_mail_sync")
    kv.value = ts
    s.add(kv); s.commit()

def _already_processed(s: SessionLocal, internet_id: str) -> bool:
    if not internet_id:
        return False
    return bool(s.execute(
        # count(*) where internet_message_id matches
        # (unique constraint ensures dedup)
        select(EmailIngest.internet_message_id).where(EmailIngest.internet_message_id == internet_id)
    ).first())

# ---------- Extraction helpers ----------
def _keywords(text: str) -> List[str]:
    keys: List[str] = []
    t = (text or "").lower()
    for k in ["mrv", "marpol", "uscg", "imo", "tier iii", "nox", "eiapp", "environment"]:
        if k in t:
            keys.append(k.upper())
    return keys

def _guess_source(text: str) -> str | None:
    t = (text or "").lower()
    if "imo" in t: return "IMO"
    if "uscg" in t: return "USCG"
    if "eu" in t or "eur-lex" in t or "commission" in t: return "EU"
    return None

def _guess_jurisdiction(text: str) -> str | None:
    t = (text or "").lower()
    if "global" in t or "imo" in t: return "Global"
    if "uscg" in t or "usa" in t or "united states" in t: return "USA"
    if "eu" in t or "european union" in t: return "EU"
    return None

def _collect_links_from_html(html: str) -> List[Dict]:
    return [{"url": m.group(1), "title": None, "link_type": "news"} for m in _URL_RE.finditer(html or "")]

# ---------- Main ingestion ----------
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
        "$orderby": "receivedDateTime DESC"
    }
    j = _graph_get(f"{root}/mailFolders/{folder_id}/messages", params=params)
    messages = j.get("value", [])

    created, skipped = 0, 0

    with SessionLocal() as s:
        last_run_ts = _last_run(s)

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

            # Extract metadata
            kw = _keywords(f"{subj}\n{body_preview}\n{body_html}")
            src = _guess_source(subj + " " + body_html)
            juris = _guess_jurisdiction(subj + " " + body_html)
            links = _collect_links_from_html(body_html)

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
            s.add(reg); s.flush()  # assign id

            # Links
            for l in links:
                s.add(RegulationLink(regulation_id=reg.id, url=l["url"], link_type=l["link_type"], title=l["title"]))

            # Dedup record
            s.add(EmailIngest(
                internet_message_id=internet_id or f"local-{reg.id}",
                regulation_id=reg.id,
                received_at=received,
                folder=GRAPH_TARGET_SUBFOLDER,
                subject=subj
            ))

            # Department classification (simple rules; extend later)
            depts = []
            if any(k in kw for k in ["MARPOL", "EIAPP", "NOX", "TIER III"]):
                depts.extend(["HSEQ", "Technical"])
            if "USCG" in kw:
                depts.append("Marine Ops")
            if "MRV" in kw:
                depts.append("HSEQ")
            reg.category = join_multi(normalize_departments(depts))

            s.add(reg); s.commit()
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

                _send_notification(reg, list(recipients), subj, sender, kw, links)

        newest_ts = messages[0].get("receivedDateTime")
        _set_last_run(s, newest_ts)
    return {"created": created, "skipped": skipped, "folder": GRAPH_TARGET_SUBFOLDER}

# ---------- Notifications ----------
def _send_notification(reg: Regulation, to_list: List[str], subj: str, sender: str, kw: List[str], links: List[Dict]):
    root = _mail_root()
    # build links list
    if links:
        links_html_items = "".join([f'<li><a href="{l["url"]}" target="_blank">{l.get("title") or l["url"]}</a></li>' for l in links])
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
        "saveToSentItems": "true"
    }
    _graph_post(f"{root}/sendMail", payload)

# ---------- Test utility ----------
def copy_last_inbox_message_to_regulations() -> str:
    """
    Copy the most recent Inbox message into Inbox/Regulations to create a test item.
    Safe server-side copy (no external email is sent).
    """
    root = _mail_root()
    j = _graph_get(f"{root}/mailFolders/inbox/messages", params={"$top": 1, "$select":"id"})
    val = j.get("value", [])
    if not val:
        return "No messages in Inbox to copy."
    mid = val[0]["id"]
    dest_id = _ensure_regulations_folder_id()
    _graph_post(f"{root}/messages/{mid}/copy", {"destinationId": dest_id})
    return "Copied last Inbox message to Inbox/Regulations."

# ---------- CLI entrypoint for scheduled runs ----------
if __name__ == "__main__":
    # Example: python agent.py
    stats = ingest_once(limit=50, dry_run=False)
    print(f"Ingested: {stats}")
