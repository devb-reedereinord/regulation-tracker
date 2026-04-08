from __future__ import annotations

from typing import Dict, List

from web_sources import WEB_SOURCES
from web_scrapers.dnv_scraper import discover_dnv_articles
from web_scrapers.gard_digest_scraper import discover_gard_articles
from web_scrapers.imo_scraper import discover_imo_news


def discover_articles() -> List[Dict]:
    discovered: List[Dict] = []

    for source in WEB_SOURCES:
        try:
            source_type = source["type"]
            if source_type in {"gard_digest", "gard_index"}:
                links = discover_gard_articles(source["base_url"])
            elif source_type == "dnv_index":
                links = discover_dnv_articles(source["base_url"])
            elif source_type == "imo_news":
                links = discover_imo_news(source["base_url"])
            else:
                print(f"[WEB] No scraper for source type '{source_type}' ({source['name']}) — skipping.")
                continue

            print(f"[WEB] {source['name']}: {len(links)} links discovered.")
            for link in links:
                discovered.append(
                    {
                        "source_name": source["name"],
                        "source_url": link,
                        "publisher": source["publisher"],
                        "jurisdiction": source["jurisdiction"],
                        "item_type": "article_url",
                    }
                )

        except Exception as exc:
            print(f"[WEB] Error scraping {source['name']}: {exc}")

    print(f"[WEB] Total links discovered across all sources: {len(discovered)}")
    return discovered
