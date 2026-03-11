import requests
from bs4 import BeautifulSoup


def discover_imo_news(url):

    r = requests.get(url, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")

    links = []

    for a in soup.select("a"):

        href = a.get("href")

        if "/en/MediaCentre/Pages/" in str(href):

            if href.startswith("/"):
                href = "https://www.imo.org" + href

            links.append(href)

    return list(set(links))
