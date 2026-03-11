import requests
from bs4 import BeautifulSoup

from web_sources import WEB_SOURCES


def fetch_index(url: str):
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.text


def extract_dnv_links(html):
    soup = BeautifulSoup(html, "lxml")

    links = []

    for a in soup.select("a"):
        href = a.get("href")

        if not href:
            continue

        if "/maritime/technical-regulatory-news/" in href and href != "/maritime/technical-regulatory-news/":

            if href.startswith("/"):
                href = "https://www.dnv.com" + href

            links.append(href)

    return list(set(links))


def discover_articles():

    discovered = []

    for source in WEB_SOURCES:

        html = fetch_index(source["base_url"])

        if "dnv.com" in source["base_url"]:
            links = extract_dnv_links(html)

        else:
            links = []

        for link in links:
            discovered.append({
                "source": source["name"],
                "url": link,
                "publisher": source["publisher"],
                "jurisdiction": source["jurisdiction"]
            })

    return discovered
