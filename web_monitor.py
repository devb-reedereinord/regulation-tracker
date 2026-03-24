from __future__ import annotations

from typing import Dict, List

from web_sources import WEB_SOURCES
from web_scrapers.dnv_scraper import discover_dnv_articles
from web_scrapers.gard_digest_scraper import discover_gard_articles


def discover_articles() -> List[Dict]:
    discovered: List[Dict] = []

    for source in WEB_SOURCES:
        try:
            if source["type"] in ("gard_index", "dnv_index"):
                # Both scrapers return a plain list of article URLs
                if source["type"] == "gard_index":
                    links = discover_gard_articles(source["base_url"])
                else:
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

