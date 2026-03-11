from web_sources import WEB_SOURCES
from web_scrapers.dnv_scraper import discover_dnv_articles
from web_scrapers.imo_scraper import discover_imo_news


def discover_articles():

    discovered = []

    for source in WEB_SOURCES:

        if source["type"] == "dnv_index":

            links = discover_dnv_articles(source["base_url"])

        elif source["type"] == "imo_news":

            links = discover_imo_news(source["base_url"])

        else:

            links = []

        for link in links:

            discovered.append({

                "url": link,
                "source": source["publisher"],
                "jurisdiction": source["jurisdiction"]

            })

    return discovered
