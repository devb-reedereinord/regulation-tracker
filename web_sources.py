"""
Registry of maritime regulatory sources to monitor
"""

WEB_SOURCES = [

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
