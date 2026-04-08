from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

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

# Gard article URLs: /en/insights/some-slug/ or /en/articles/some-slug/
# Requires at least 4 chars in the slug so plain category roots are excluded
_ARTICLE_RE = re.compile(
    r"gard\.no/(en/)?(insights|articles)/[^/\s?#]{4,}/?$",
    re.I,
)

# Known Gard RSS/Atom feed candidates (tried in order)
_GARD_RSS_URLS = [
    "https://www.gard.no/rss/",
    "https://gard.no/rss/",
    "https://www.gard.no/feed/",
    "https://gard.no/feed/",
]


def _fetch_html_playwright(url: str) -> str:
    """Render the Gard listing page with headless Chromium so JS card links appear."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={
            "Accept-Language": "en-GB,en;q=0.9",
        })
        page.goto(url, timeout=45_000, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def _fetch_html_requests(url: str) -> str:
    """Fallback plain HTTP fetch with realistic browser headers."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def _fetch_gard_rss() -> list[str]:
    """
    Try known Gard RSS/Atom feed URLs and extract article links.
    Returns a deduplicated list of article URLs, or [] if all feeds fail.
    """
    atom_ns = "http://www.w3.org/2005/Atom"
    for rss_url in _GARD_RSS_URLS:
        try:
            r = requests.get(rss_url, headers=HEADERS, timeout=15)
            if r.status_code != 200:
                continue
            content = r.text
            if "<rss" not in content and "<feed" not in content and "<channel" not in content:
                continue
            root = ET.fromstring(content)
            links: list[str] = []

            # RSS 2.0: //channel/item/link
            for item in root.iter("item"):
                link_el = item.find("link")
                if link_el is not None and link_el.text:
                    href = link_el.text.strip()
                    if _ARTICLE_RE.search(href):
                        links.append(href)

            # Atom: //entry/link[@href]
            for entry in root.iter(f"{{{atom_ns}}}entry"):
                link_el = entry.find(f"{{{atom_ns}}}link")
                if link_el is not None:
                    href = link_el.get("href", "")
                    if href and _ARTICLE_RE.search(href):
                        links.append(href)

            if links:
                found = list(dict.fromkeys(links))
                print(f"[GARD] RSS fallback: {len(found)} links from {rss_url}")
                return found
        except Exception as e:
            print(f"[GARD] RSS attempt failed ({rss_url}): {e}")
            continue
    return []


def discover_gard_articles(url: str) -> list[str]:
    """
    Scrape the Gard articles/insights listing page and return a deduplicated
    list of individual article URLs.

    Priority: Playwright (JS-rendered) → RSS feed → plain requests HTML.
    """
    # 1. Try Playwright (handles JS-rendered card links)
    try:
        html = _fetch_html_playwright(url)
    except Exception as _pw_err:
        print(f"[GARD] Playwright unavailable ({_pw_err}), trying RSS fallback.")
        html = ""

    # Extract links from Playwright HTML if we got it
    if html:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if href.startswith("/"):
                href = "https://gard.no" + href
            if _ARTICLE_RE.search(href):
                links.append(href)
        found = list(dict.fromkeys(links))
        if found:
            print(f"[GARD] Found {len(found)} article links via Playwright from {url}")
            return found
        print("[GARD] Playwright returned HTML but 0 matching links — trying RSS.")

    # 2. Try RSS feed (works without Playwright)
    rss_links = _fetch_gard_rss()
    if rss_links:
        return rss_links

    # 3. Last resort: plain requests HTML parse
    print("[GARD] Falling back to plain requests HTML parse.")
    html = _fetch_html_requests(url)
    if not html:
        print("[GARD] No HTML returned — 0 articles found.")
        return []

    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if href.startswith("/"):
            href = "https://gard.no" + href
        if _ARTICLE_RE.search(href):
            links.append(href)

    found = list(dict.fromkeys(links))
    print(f"[GARD] Found {len(found)} article links from {url}")
    return found
