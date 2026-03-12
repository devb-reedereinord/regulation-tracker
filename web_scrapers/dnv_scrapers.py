import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}


def discover_dnv_articles(url):

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)

        if r.status_code != 200:
            return []

        soup = BeautifulSoup(r.text, "lxml")

        links = []

        for a in soup.select("a"):

            href = a.get("href")

            if not href:
                continue

            if "/maritime/technical-regulatory-news/" in href:

                if href.startswith("/"):
                    href = "https://www.dnv.com" + href

                links.append(href)

        return list(set(links))

    except Exception:
        return []
