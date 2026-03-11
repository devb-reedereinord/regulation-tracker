from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

SECTION_RE = re.compile(
    r"Changes\s+from\s+(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})",
    flags=re.I,
)


def _normalize_ws(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _parse_effective_date(section_heading: str) -> Optional[str]:
    """
    Converts:
        'Changes from 1 January 2026'
    into:
        '2026-01-01'
    """
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
    """
    Gard pages can shift structure a bit, so try a few likely containers.
    Fallback to soup.body.
    """
    candidates = [
        "main",
        "article",
        '[role="main"]',
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
    if tag.name not in {"h2", "h3"}:
        return False
    txt = _normalize_ws(tag.get_text(" ", strip=True))
    return bool(SECTION_RE.search(txt))


def _extract_item_title_and_links(p_tag: Tag, base_url: str) -> Tuple[str, str, List[Dict[str, str]]]:
    """
    Example first paragraph pattern on the page:
      <a>MSC.532(107)</a>: SOLAS II-1/3-13 (Lifting Appliances and Anchor Handling Winches)

    We treat:
    - link text(s) + text before colon as references
    - text after colon as item title
    """
    full_text = _normalize_ws(p_tag.get_text(" ", strip=True))

    links: List[Dict[str, str]] = []
    for a in p_tag.find_all("a", href=True):
        href = _absolute_url(a["href"], base_url)
        label = _normalize_ws(a.get_text(" ", strip=True))
        if href:
            links.append(
                {
                    "url": href,
                    "title": label or href,
                    "link_type": "guidance",
                }
            )

    if ":" in full_text:
        left, right = full_text.split(":", 1)
        ref = _normalize_ws(left)
        title = _normalize_ws(right)
        return title or full_text, ref, links

    return full_text, "", links


def discover_gard_digest_items(base_url: str) -> List[Dict]:
    """
    Returns one item per regulatory entry on the Gard digest page.

    Output fields:
    - source_name
    - source_url
    - article_title
    - effective_date
    - item_title
    - reference
    - summary
    - supporting_links
    - publisher
    - jurisdiction
    """
    r = requests.get(base_url, headers=HEADERS, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")
    container = _find_main_content_container(soup)
    article_title = _extract_page_title(soup)

    # Read direct descendants in document order for stable grouping
    elements = container.find_all(["h2", "h3", "p"], recursive=True)

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

        # Gard digest entries begin with a paragraph containing a reference/title line.
        # We only start collecting an item if we are inside a recognized date section.
        if el.name == "p" and current_effective_date:
            txt = _normalize_ws(el.get_text(" ", strip=True))

            # Heuristic: start item when paragraph has a colon and either:
            # - contains an anchor, or
            # - begins with something reference-like
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

                        # stop if next paragraph looks like a new item
                        if (
                            (nxt.find("a", href=True) and ":" in nxt_txt)
                            or re.match(r"^[A-Z0-9./() -]{4,}:", nxt_txt)
                        ):
                            break

                        if nxt_txt:
                            summary_parts.append(nxt_txt)

                    j += 1

                items.append(
                    {
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
                    }
                )

                i = j
                continue

        i += 1

    # Deduplicate by (effective_date, item_title)
    seen = set()
    deduped: List[Dict] = []
    for item in items:
        key = (item["effective_date"], item["item_title"].lower())
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped
