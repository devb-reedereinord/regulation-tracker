import requests
from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def discover_imo_news(url):

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

            if "/en/MediaCentre/" in str(href):

                if href.startswith("/"):
                    href = "https://www.imo.org" + href

                links.append(href)

        return list(set(links))

    except Exception:

        # prevent crash of entire crawler
        return []
