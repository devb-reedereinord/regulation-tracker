from __future__ import annotations

import re

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


def discover_gard_articles(url: str) -> list[str]:
    """
    Scrape the Gard articles/insights listing page and return a deduplicated
    list of individual article URLs.

    Uses Playwright to render JS-loaded article cards; falls back to requests.
    Article links follow /en/insights/slug/ or /en/articles/slug/ patterns.
    """
    # Try Playwright first (handles JS-rendered card links)
    try:
        html = _fetch_html_playwright(url)
    except Exception as _pw_err:
        print(f"[GARD] Playwright unavailable ({_pw_err}), falling back to requests.")
        html = _fetch_html_requests(url)

    if not html:
        print("[GARD] No HTML returned — 0 articles found.")
        return []

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []

    for a in soup.select("a[href]"):
        href = a.get("href", "")
        # Normalise relative URLs
        if href.startswith("/"):
            href = "https://gard.no" + href
        if _ARTICLE_RE.search(href):
            links.append(href)

    found = list(dict.fromkeys(links))   # deduplicate, preserve order
    print(f"[GARD] Found {len(found)} article links from {url}")
    return found
