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

# Individual article URLs look like /news/YYYY/article-slug/
# e.g. /news/2026/new-regulations-for-newbuilding-speed-trials-enter-into-force-on-1-may-2026/
_ARTICLE_RE = re.compile(r"/news/\d{4}/[^/\s]+/?$", re.I)


def discover_dnv_articles(url: str) -> list[str]:
    """
    Scrape the DNV maritime technical-regulatory news index page and return
    a deduplicated list of individual article URLs.

    Individual articles follow /news/YYYY/slug/ — not the index page URL itself
    (/maritime/technical-regulatory-news/) which was the old (wrong) filter.
    """
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "lxml")
        links: list[str] = []

        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if not _ARTICLE_RE.search(href):
                continue
            if href.startswith("/"):
                href = "https://www.dnv.com" + href
            if href.startswith("https://www.dnv.com"):
                links.append(href)

        # deduplicate, preserve insertion order
        return list(dict.fromkeys(links))

    except Exception:
        return []
