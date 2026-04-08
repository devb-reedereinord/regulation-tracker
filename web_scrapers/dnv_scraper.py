from __future__ import annotations

import re
import subprocess
import sys
from urllib.parse import urljoin, urlsplit, urlunsplit

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

# DNV article URL patterns vary over time; keep matcher intentionally broad.
_ARTICLE_YEAR_NEWS_RE = re.compile(r"/news/\d{4}/", re.I)
_PLAYWRIGHT_CHROMIUM_READY: bool | None = None


def _ensure_playwright_chromium() -> bool:
    """
    Ensure Chromium binaries used by Playwright are present.

    Useful in ephemeral environments where browser caches are wiped between runs.
    """
    global _PLAYWRIGHT_CHROMIUM_READY
    if _PLAYWRIGHT_CHROMIUM_READY is not None:
        return _PLAYWRIGHT_CHROMIUM_READY

    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        _PLAYWRIGHT_CHROMIUM_READY = result.returncode == 0
        if not _PLAYWRIGHT_CHROMIUM_READY:
            err = (result.stderr or result.stdout or "unknown error").strip()
            print(f"[DNV] Playwright Chromium install failed: {err[:300]}")
    except Exception as exc:
        _PLAYWRIGHT_CHROMIUM_READY = False
        print(f"[DNV] Playwright Chromium install exception: {exc}")

    return _PLAYWRIGHT_CHROMIUM_READY


def _render_dnv_html(url: str) -> str:
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


def _fetch_html_playwright(url: str) -> str:
    """
    Render the DNV listing page with headless Chromium so JS card links are present.

    Retries once after installing Chromium if browser binaries are missing.
    """
    try:
        return _render_dnv_html(url)
    except Exception as first_err:
        err_msg = str(first_err)
        if "Executable doesn't exist" not in err_msg:
            raise

        print("[DNV] Playwright Chromium missing; attempting one-time install.")
        if not _ensure_playwright_chromium():
            raise

        return _render_dnv_html(url)


def _fetch_html_requests(url: str) -> str:
    """Fallback plain HTTP fetch."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def discover_dnv_articles(url: str) -> list[str]:
    """
    Scrape the DNV maritime technical-regulatory news index page and return
    a deduplicated list of individual article URLs.

    Uses Playwright to render JS-loaded article cards; falls back to requests.
    Article links follow /news/YYYY/slug/ not the index URL itself.

    NOTE: DNV's listing page is fully JS-rendered. Plain requests will return
    0 results. If Playwright is unavailable, install it with:
        pip install playwright && playwright install chromium
    """
    # Try Playwright first (handles JS-rendered article card links)
    try:
        html = _fetch_html_playwright(url)
    except Exception as _pw_err:
        print(
            f"[DNV] Playwright unavailable ({_pw_err}). "
            "DNV requires Playwright to render JS content. "
            "Fix: pip install playwright && playwright install chromium"
        )
        html = _fetch_html_requests(url)

    if not html:
        return []

    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []

    def _normalize(href: str) -> str:
        # Build absolute URL, strip query/fragment for stable deduplication.
        absolute = urljoin(url, href)
        parts = urlsplit(absolute)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    def _is_dnv_article(href: str) -> bool:
        if not href:
            return False
        normalized = _normalize(href)
        parts = urlsplit(normalized)
        if "dnv.com" not in parts.netloc.lower():
            return False

        path = parts.path.lower()
        # Exclude listing pages and generic hubs.
        if path.rstrip("/") in {
            "/maritime/technical-regulatory-news",
            "/maritime/news",
            "/news",
        }:
            return False

        # Prefer year-based news paths, but allow broader maritime news URLs.
        return bool(
            _ARTICLE_YEAR_NEWS_RE.search(path)
            or ("/maritime/news/" in path and len(path.strip("/").split("/")) >= 4)
        )

    for a in soup.select("a[href], [data-href]"):
        href = a.get("href") or a.get("data-href") or ""
        if not _is_dnv_article(href):
            continue
        links.append(_normalize(href))

    return list(dict.fromkeys(links))   # deduplicate, preserve order
