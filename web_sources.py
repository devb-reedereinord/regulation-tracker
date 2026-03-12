"""
Registry of maritime regulatory sources to monitor
"""

WEB_SOURCES = [
    {
        "name": "Gard Shipping Changes 2026",
        "base_url": "https://gard.no/en/insights/what-is-changing-for-shipping-in-2026-1/",
        "type": "gard_digest",
        "publisher": "Gard",
        "jurisdiction": "Global",
    },

    {
        "name": "DNV Technical Regulatory News",
        "base_url": "https://www.dnv.com/maritime/technical-regulatory-news/",
        "type": "dnv_index",
        "publisher": "DNV",
        "jurisdiction": "Global"
    },

    {
        "name": "IMO News",
        "base_url": "https://www.imo.org/en/MediaCentre/Pages/WhatsNew.aspx",
        "type": "imo_news",
        "publisher": "IMO",
        "jurisdiction": "Global"
    },

    {
        "name": "EU Maritime News",
        "base_url": "https://transport.ec.europa.eu/news-events/news_en",
        "type": "eu_news",
        "publisher": "EU",
        "jurisdiction": "EU"
    }

]
