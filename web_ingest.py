import requests
from bs4 import BeautifulSoup

from sqlalchemy import select

from models import SessionLocal, Regulation, RegulationLink

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def download_article(url):

    try:

        r = requests.get(url, headers=HEADERS, timeout=30)

        if r.status_code != 200:
            return None, None

        soup = BeautifulSoup(r.text, "lxml")

        title = soup.title.text if soup.title else url

        paragraphs = [p.get_text() for p in soup.select("p")]

        text = " ".join(paragraphs)

        return title, text

    except Exception:
        return None, None


def ingest_web_article(item):

    with SessionLocal() as s:

        exists = s.execute(
            select(Regulation).where(Regulation.title == item["url"])
        ).first()

        if exists:
            return False

        title, text = download_article(item["url"])

        if not title:
            return False
