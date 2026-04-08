from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select

from models import SessionLocal, Regulation, RegulationLink

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
}


def _normalize_ws(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _safe_date(date_str: Optional[str]):
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def download_article(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Fetch an article page and return (title, body_text)."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None, None

        soup = BeautifulSoup(r.text, "lxml")
        title = soup.title.get_text(" ", strip=True) if soup.title else url
        paragraphs = [
            _normalize_ws(p.get_text(" ", strip=True))
            for p in soup.select("p")
        ]
        text = "\n\n".join([p for p in paragraphs if p])
        return title, text

    except Exception:
        return None, None


def _extract_web_article_with_ai(
    title: str, text: str, url: str, source: str
) -> dict:
    """
    Call OpenAI to extract structured regulation info from a web article.
    Returns a dict with the same keys as the PDF extraction schema,
    or {"skip": True} if the article is not regulatory.
    """
    try:
        import openai
        from config import OPENAI_API_KEY, OPENAI_MODEL
        try:
            from agent import COMPANY_PROFILE
        except Exception:
            COMPANY_PROFILE = (
                "Company: Reederei Nord Group (ship management, Netherlands). "
                "Fleet: Container Vessels, Bulk Carriers, Tankers."
            )

        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        prompt = f"""{COMPANY_PROFILE}

SOURCE: {source}
URL: {url}
TITLE: {title}

ARTICLE TEXT (up to 12 000 chars):
{text[:12000]}

You are a maritime regulatory analyst. Extract the regulatory obligation from this article.

Return a JSON object with EXACTLY these keys:
{{
  "title": "concise regulation title (max 120 chars)",
  "description": "## Key requirements\\n<bullet points>\\n\\n## Applies to\\n<vessel types / operations>\\n\\n## Entry into force\\n<date and context>\\n\\n## Reederei Nord relevance\\n<specific impact on Container Vessels / Bulk Carriers / Tankers>",
  "due_date": "YYYY-MM-DD or null",
  "force_status": "In Force | Upcoming | Draft | Unknown",
  "instruments": ["MSC.532(107)", "MEPC.377(80)"],
  "applicable_fleet": ["Container Vessels", "Bulk Carriers", "Tankers"],
  "departments": ["HSEQ", "Technical", "Marine Ops", "Crewing", "HR"],
  "construction_restriction": "text or null",
  "engine_restriction": "text or null"
}}

Rules:
- force_status: "In Force" if effective date is past or article says already in force;
  "Upcoming" if a concrete future date is given; "Draft" if described as proposed/draft/expected;
  otherwise "Unknown".
- applicable_fleet: include only fleet types genuinely affected; use all three if genuinely unclear.
- departments: choose only departments whose work is directly impacted.
- If this article does NOT describe a regulatory requirement, obligation, amendment, or
  compliance deadline relevant to shipping, return {{"skip": true}} instead.
"""
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)

    except Exception as e:
        # AI failure — return minimal structure so article is not silently dropped
        return {
            "title": title,
            "description": (text or "")[:3000],
            "due_date": None,
            "force_status": "Unknown",
            "instruments": [],
            "applicable_fleet": ["Container Vessels", "Bulk Carriers", "Tankers"],
            "departments": ["HSEQ"],
            "construction_restriction": None,
            "engine_restriction": None,
            "_ai_error": str(e),
        }


def _reg_exists(s, title: str, source: str) -> bool:
    row = s.execute(
        select(Regulation.id).where(
            Regulation.title == title,
            Regulation.source == source,
        ).limit(1)
    ).first()
    return bool(row)


def _url_exists(s, url: str) -> bool:
    """Check if a URL has already been ingested (exists in RegulationLink)."""
    row = s.execute(
        select(RegulationLink.id).where(RegulationLink.url == url).limit(1)
    ).first()
    return bool(row)


def _safe_set(obj, attr: str, val) -> None:
    """Set attribute only if the ORM model actually has it (guards against stale deployments)."""
    if hasattr(obj, attr):
        setattr(obj, attr, val)


def ingest_web_article(item: Dict) -> bool:
    """
    Persist a discovered web item to the DB.

    Supports two shapes:
    1) Structured digest item (Gard) — has "item_title"
    2) Plain article URL (DNV / other) — has "source_url", no "item_title"

    Returns True if a new record was created.
    """
    from models import join_multi

    # Strip internal debug/metadata fields
    item = {k: v for k, v in item.items() if not k.startswith("_")}

    with SessionLocal() as s:
        # ── Case 1: structured digest item (Gard) ────────────────────────────
        if item.get("item_title"):
            title  = item.get("item_title", "").strip()
            source = item.get("publisher") or item.get("source_name") or "Web"
            if not title:
                return False
            if _reg_exists(s, title, source):
                return False

            reg = Regulation(
                title=title,
                source=source,
                jurisdiction=item.get("jurisdiction"),
                category="HSEQ",
                effective_date=_safe_date(item.get("effective_date")),
                summary=(item.get("summary") or "")[:4000],
                status="Open",
            )
            s.add(reg)
            s.flush()

            main_url = item.get("source_url")
            if main_url:
                s.add(RegulationLink(
                    regulation_id=reg.id,
                    url=main_url,
                    link_type="news",
                    title=item.get("article_title") or "Source page",
                ))

            for lnk in item.get("supporting_links", []) or []:
                lnk_url = lnk.get("url")
                if lnk_url:
                    s.add(RegulationLink(
                        regulation_id=reg.id,
                        url=lnk_url,
                        link_type=lnk.get("link_type", "guidance"),
                        title=lnk.get("title"),
                    ))

            s.commit()
            return True

        # ── Case 2: plain article URL (DNV / other) ───────────────────────────
        url = item.get("source_url") or item.get("url")
        if not url:
            return False

        # Fast URL-based dedup: skip download + AI if already ingested
        if _url_exists(s, url):
            print(f"[INGEST] Already seen URL, skipping: {url}")
            return False

        source = item.get("publisher") or item.get("source") or "Web"
        article_title, text = download_article(url)
        if not article_title:
            return False

        # AI extraction — process every article; discard non-regulatory ones
        ai_data = _extract_web_article_with_ai(article_title, text or "", url, source)
        if ai_data.get("skip"):
            return False

        # Use AI-refined title if provided
        final_title = (ai_data.get("title") or article_title).strip()[:250] or article_title
        if _reg_exists(s, final_title, source):
            return False

        reg = Regulation(
            title=final_title,
            source=source,
            jurisdiction=item.get("jurisdiction", "Global"),
            category=join_multi(ai_data.get("departments") or ["HSEQ"]),
            effective_date=_safe_date(ai_data.get("due_date")),
            summary=ai_data.get("description") or (text or "")[:4000],
            status="Open",
        )
        _safe_set(reg, "fleet_tags",               join_multi(ai_data.get("applicable_fleet") or []))
        _safe_set(reg, "force_status",             ai_data.get("force_status") or "Unknown")
        _safe_set(reg, "instruments",              join_multi(ai_data.get("instruments") or []))
        _safe_set(reg, "construction_restriction", ai_data.get("construction_restriction"))
        _safe_set(reg, "engine_restriction",        ai_data.get("engine_restriction"))

        s.add(reg)
        s.flush()

        s.add(RegulationLink(
            regulation_id=reg.id,
            url=url,
            link_type="news",
            title="Source article",
        ))

        s.commit()
        return True


def discover_and_preview_web_articles() -> list[dict]:
    """
    Discover articles from all sources, download + AI-extract each one,
    and return a list of preview dicts for the web scanner review table in app.py.

    Each dict contains everything needed to render the review table row AND
    to save the record if the user confirms.
    """
    from web_monitor import discover_articles

    raw_items = discover_articles()
    previews = []

    for item in raw_items:
        clean = {k: v for k, v in item.items() if not k.startswith("_")}

        # Case 1: Gard structured digest — already structured, no AI needed
        if clean.get("item_title"):
            previews.append({
                "_ob": clean,
                "_url": clean.get("source_url", ""),
                "_source": clean.get("publisher") or clean.get("source_name") or "Gard",
                "is_skip": False,
                "title": clean["item_title"],
                "due_date": clean.get("effective_date"),
                "force_status": "Unknown",
                "applicable_fleet": [],
                "departments": ["HSEQ"],
                "description": clean.get("summary") or "",
            })
            continue

        # Case 2: plain article URL — download + AI
        url = clean.get("source_url") or clean.get("url")
        if not url:
            continue

        # Skip URLs already in the DB
        with SessionLocal() as _s:
            if _url_exists(_s, url):
                continue

        source = clean.get("publisher") or clean.get("source") or "Web"
        article_title, text = download_article(url)
        if not article_title:
            continue

        ai_data = _extract_web_article_with_ai(article_title, text or "", url, source)
        previews.append({
            "_ob": {**clean, **ai_data, "_original_url": url},
            "_url": url,
            "_source": source,
            "is_skip": bool(ai_data.get("skip")),
            "title": (ai_data.get("title") or article_title)[:250],
            "due_date": ai_data.get("due_date"),
            "force_status": ai_data.get("force_status") or "Unknown",
            "applicable_fleet": ai_data.get("applicable_fleet") or [],
            "departments": ai_data.get("departments") or [],
            "description": ai_data.get("description") or "",
        })

    return previews
