from __future__ import annotations

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
    )
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


def _reg_exists(s, title: str, source: str) -> bool:
    row = s.execute(
        select(Regulation.id).where(
            Regulation.title == title,
            Regulation.source == source,
        ).limit(1)
    ).first()
    return bool(row)


def ingest_web_article(item: Dict) -> bool:
    """
    Supports two shapes:

    1) Digest item (Gard):
       {
         "item_title": "...",
         "publisher": "Gard",
         "jurisdiction": "Global",
         "effective_date": "2026-01-01",
         "summary": "...",
         "source_url": "...",
         "article_title": "...",
         "supporting_links": [...]
       }

    2) Simple article link (DNV / other index pages):
       {
         "source_name": "...",
         "source_url": "https://...",
         "publisher": "DNV",
         "jurisdiction": "Global",
         "item_type": "article_url"
       }
    """
    with SessionLocal() as s:
        # ----------------------------
        # Case 1: structured digest item
        # ----------------------------
        if item.get("item_title"):
            title = item.get("item_title", "").strip()
            source = item.get("publisher") or item.get("source_name") or "Web"
            jurisdiction = item.get("jurisdiction")
            summary = item.get("summary") or ""
            effective_date = _safe_date(item.get("effective_date"))

            if not title:
                return False

            if _reg_exists(s, title, source):
                return False

            reg = Regulation(
                title=title,
                source=source,
                jurisdiction=jurisdiction,
                category="HSEQ",
                effective_date=effective_date,
                summary=summary[:4000],
                status="Open",
            )
            s.add(reg)
            s.flush()

            # Main source page
            main_url = item.get("source_url")
            if main_url:
                s.add(
                    RegulationLink(
                        regulation_id=reg.id,
                        url=main_url,
                        link_type="news",
                        title=item.get("article_title") or "Source page",
                    )
                )

            # Supporting links
            for lnk in item.get("supporting_links", []) or []:
                url = lnk.get("url")
                if not url:
                    continue

                s.add(
                    RegulationLink(
                        regulation_id=reg.id,
                        url=url,
                        link_type=lnk.get("link_type", "guidance"),
                        title=lnk.get("title"),
                    )
                )

            s.commit()
            return True

        # ----------------------------
        # Case 2: plain article URL
        # ----------------------------
        url = item.get("source_url") or item.get("url")
        if not url:
            return False

        source = item.get("publisher") or item.get("source") or "Web"
        jurisdiction = item.get("jurisdiction")

        article_title, text = download_article(url)
        if not article_title:
            return False

        if _reg_exists(s, article_title, source):
            return False

        reg = Regulation(
            title=article_title,
            source=source,
            jurisdiction=jurisdiction,
            category="HSEQ",
            summary=(text or "")[:4000],
            status="Open",
        )
        s.add(reg)
        s.flush()

        s.add(
            RegulationLink(
                regulation_id=reg.id,
                url=url,
                link_type="news",
                title="Source article",
            )
        )

        s.commit()
        return True
