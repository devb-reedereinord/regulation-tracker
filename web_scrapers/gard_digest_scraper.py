from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

# Full browser headers to reduce bot-detection rejections
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Referer": "https://www.google.com/",
}

SECTION_RE = re.compile(
    r"Changes\s+from\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    flags=re.I,
)

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def _normalize_ws(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _parse_effective_date(section_heading: str) -> Optional[str]:
    m = SECTION_RE.search(section_heading or "")
    if not m:
        return None
    day = int(m.group(1))
    month_name = m.group(2)
    year = int(m.group(3))
    try:
        dt = datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def _absolute_url(href: str, base_url: str) -> str:
    if not href:
        return ""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    if href.startswith("/"):
        return "https://gard.no" + href
    return base_url.rstrip("/") + "/" + href.lstrip("/")


def _find_main_content_container(soup: BeautifulSoup) -> Tag:
    candidates = [
        "main",
        "article",
        '[role="main"]',
        ".article-content",
        ".content-body",
        ".entry-content",
        "#content",
        ".main-content",
        ".page-content",
    ]
    for sel in candidates:
        node = soup.select_one(sel)
        if node:
            return node
    return soup.body or soup


def _extract_page_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return _normalize_ws(h1.get_text(" ", strip=True))
    if soup.title:
        return _normalize_ws(soup.title.get_text(" ", strip=True))
    return "Gard regulatory digest"


def _is_section_heading(tag: Tag) -> bool:
    if not isinstance(tag, Tag):
        return False
    if tag.name not in _HEADING_TAGS:
        return False
    txt = _normalize_ws(tag.get_text(" ", strip=True))
    return bool(SECTION_RE.search(txt))


def _extract_item_title_and_links(
    p_tag: Tag, base_url: str
) -> Tuple[str, str, List[Dict[str, str]]]:
    full_text = _normalize_ws(p_tag.get_text(" ", strip=True))
    links: List[Dict[str, str]] = []
    for a in p_tag.find_all("a", href=True):
        href = _absolute_url(a["href"], base_url)
        label = _normalize_ws(a.get_text(" ", strip=True))
        if href:
            links.append({"url": href, "title": label or href, "link_type": "guidance"})
    if ":" in full_text:
        left, right = full_text.split(":", 1)
        ref = _normalize_ws(left)
        title = _normalize_ws(right)
        return title or full_text, ref, links
    return full_text, "", links


def _fallback_extract(container: Tag, base_url: str, article_title: str) -> List[Dict]:
    items: List[Dict] = []
    seen_urls: set = set()
    current_heading = article_title
    for el in container.find_all(True):
        if isinstance(el, Tag) and el.name in _HEADING_TAGS:
            txt = _normalize_ws(el.get_text(" ", strip=True))
            if txt:
                current_heading = txt
        elif isinstance(el, Tag) and el.name == "a":
            href = el.get("href", "")
            if not href or href.startswith("#") or href.startswith("mailto:"):
                continue
            abs_url = _absolute_url(href, base_url)
            if not abs_url or abs_url in seen_urls:
                continue
            label = _normalize_ws(el.get_text(" ", strip=True))
            if not label or len(label) < 5:
                continue
            seen_urls.add(abs_url)
            items.append({
                "source_name": "Gard Shipping Changes 2026",
                "source_url": base_url,
                "article_title": article_title,
                "effective_date": None,
                "section_heading": current_heading,
                "item_title": label,
                "reference": "",
                "summary": f"From section: {current_heading}",
                "supporting_links": [{"url": abs_url, "title": label, "link_type": "guidance"}],
                "publisher": "Gard",
                "jurisdiction": "Global",
                "_fallback": True,
            })
    return items


# ── HTML fetchers ─────────────────────────────────────────────────────────────

def _fetch_with_playwright(url: str) -> str:
    """
    Render the page with a headless Chromium browser so JavaScript hydration
    completes before we parse HTML.  Requires `playwright` in requirements.txt
    and `chromium` in packages.txt (Streamlit Cloud) or `playwright install chromium`.
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={
            "Accept-Language": "en-GB,en;q=0.9",
        })
        page.goto(url, timeout=30_000, wait_until="domcontentloaded")
        # Give JS 3 s to populate the DOM
        page.wait_for_timeout(3000)
        html = page.content()
        browser.close()
    return html


def _fetch_with_requests(url: str) -> str:
    """Plain HTTP fetch with realistic browser headers (fallback)."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code == 200:
        return r.text
    return ""


def _fetch_html(url: str) -> str:
    """Try Playwright first; fall back to requests if Playwright is unavailable."""
    try:
        return _fetch_with_playwright(url)
    except Exception as _pw_err:
        print(f"[GARD] Playwright unavailable ({_pw_err}), falling back to requests.")
        return _fetch_with_requests(url)


# ── Main entry point ──────────────────────────────────────────────────────────

def discover_gard_digest_items(base_url: str) -> List[Dict]:
    """
    Returns one item per regulatory entry on the Gard digest page.
    Uses Playwright to render JS-heavy pages; falls back to requests.
    """
    html = _fetch_html(base_url)
    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    container = _find_main_content_container(soup)
    article_title = _extract_page_title(soup)

    elements = container.find_all(list(_HEADING_TAGS) + ["p"], recursive=True)

    debug_headings = [
        _normalize_ws(el.get_text(" ", strip=True))
        for el in elements
        if el.name in _HEADING_TAGS
    ]

    items: List[Dict] = []
    current_section_heading: Optional[str] = None
    current_effective_date: Optional[str] = None

    i = 0
    while i < len(elements):
        el = elements[i]

        if _is_section_heading(el):
            current_section_heading = _normalize_ws(el.get_text(" ", strip=True))
            current_effective_date = _parse_effective_date(current_section_heading)
            i += 1
            continue

        if el.name == "p" and current_effective_date:
            txt = _normalize_ws(el.get_text(" ", strip=True))

            starts_item = False
            if el.find("a", href=True) and ":" in txt:
                starts_item = True
            elif ":" in txt and re.match(r"^[A-Z0-9./() -]{4,}:", txt):
                starts_item = True

            if starts_item:
                item_title, reference, links = _extract_item_title_and_links(el, base_url)

                summary_parts: List[str] = []
                j = i + 1
                while j < len(elements):
                    nxt = elements[j]
                    if _is_section_heading(nxt):
                        break
                    if nxt.name == "p":
                        nxt_txt = _normalize_ws(nxt.get_text(" ", strip=True))
                        if (
                            (nxt.find("a", href=True) and ":" in nxt_txt)
                            or re.match(r"^[A-Z0-9./() -]{4,}:", nxt_txt)
                        ):
                            break
                        if nxt_txt:
                            summary_parts.append(nxt_txt)
                    j += 1

                items.append({
                    "source_name": "Gard Shipping Changes 2026",
                    "source_url": base_url,
                    "article_title": article_title,
                    "effective_date": current_effective_date,
                    "section_heading": current_section_heading,
                    "item_title": item_title,
                    "reference": reference,
                    "summary": "\n\n".join(summary_parts).strip(),
                    "supporting_links": links,
                    "publisher": "Gard",
                    "jurisdiction": "Global",
                })
                i = j
                continue

        i += 1

    # Deduplicate
    seen: set = set()
    deduped: List[Dict] = []
    for item in items:
        key = (item["effective_date"], item["item_title"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    if not deduped:
        print(
            f"[GARD] Structured parse found 0 items. "
            f"Headings seen: {debug_headings[:20]}. "
            f"Running fallback link extraction."
        )
        deduped = _fallback_extract(container, base_url, article_title)

    if deduped:
        deduped[0]["_debug_headings"] = debug_headings

    return deduped
