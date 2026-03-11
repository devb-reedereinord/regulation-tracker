from __future__ import annotations

from typing import Dict, List

from web_sources import WEB_SOURCES
from web_scrapers.dnv_scraper import discover_dnv_articles
from web_scrapers.gard_digest_scraper import discover_gard_digest_items


def discover_articles() -> List[Dict]:
    """
    Returns a unified list of discovered records.

    For digest pages (like Gard), each returned dict is already an item.
    For index pages (like DNV), each returned dict is a link to an article page.
    """
    discovered: List[Dict] = []

    for source in WEB_SOURCES:
        try:
            source_type = source["type"]

            if source_type == "gard_digest":
                items = discover_gard_digest_items(source["base_url"])
                discovered.extend(items)

            elif source_type == "dnv_index":
                links = discover_dnv_articles(source["base_url"])
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
            print(f"Error scraping {source['name']}: {exc}")

    return discovered
