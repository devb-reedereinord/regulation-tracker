import requests
from bs4 import BeautifulSoup

from sqlalchemy import select

from models import SessionLocal, Regulation, RegulationLink


def download_article(url):

    r = requests.get(url, timeout=30)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "lxml")

    title = soup.title.text if soup.title else url

    paragraphs = [p.get_text() for p in soup.select("p")]

    text = " ".join(paragraphs)

    return title, text


def ingest_web_article(item):

    with SessionLocal() as s:

        exists = s.execute(
            select(Regulation).where(Regulation.title == item["url"])
        ).first()

        if exists:
            return False

        title, text = download_article(item["url"])

        reg = Regulation(
            title=title,
            source=item["source"],
            jurisdiction=item["jurisdiction"],
            category="HSEQ",
            summary=text[:1000],
            status="Open"
        )

        s.add(reg)
        s.flush()

        s.add(RegulationLink(
            regulation_id=reg.id,
            url=item["url"],
            link_type="news",
            title="Source article"
        ))

        s.commit()

    return True
