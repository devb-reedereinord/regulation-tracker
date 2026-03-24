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
    "Accept-Language": "en-US,en;q=0.5",
}

# Individual article URLs: /news/YYYY/article-slug/
_ARTICLE_RE = re.compile(r"/news/\d{4}/[^/\s]+/?$", re.I)


def _fetch_html_playwright(url: str) -> str:
    """Render the DNV listing page with headless Chromium so JS card links are present."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        })
        page.goto(url, timeout=45_000, wait_until="networkidle")
        html = page.content()
        browser.close()
    return html


def _fetch_html_requests(url: str) -> str:
    """Fallback plain HTTP fetch."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    return r.text if r.status_code == 200 else ""


def discover_dnv_articles(url: str) -> list[str]:
    """
    Scrape the DNV maritime technical-regulatory news index page and return
    a deduplicated list of individual article URLs.

    Uses Playwright to render JS-loaded article cards; falls back to requests.
    Article links follow /news/YYYY/slug/ not the index URL itself.
    """
    # Try Playwright first (handles JS-rendered article card links)
    try:
        html = _fetch_html_playwright(url)
    except Exception as _pw_err:
        print(f"[DNV] Playwright unavailable ({_pw_err}), falling back to requests.")
        html = _fetch_html_requests(url)

    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []

    for a in soup.select("a[href]"):
        href = a.get("href", "")
        if not _ARTICLE_RE.search(href):
            continue
        if href.startswith("/"):
            href = "https://www.dnv.com" + href
        if href.startswith("https://www.dnv.com"):
            links.append(href)

    return list(dict.fromkeys(links))   # deduplicate, preserve order
