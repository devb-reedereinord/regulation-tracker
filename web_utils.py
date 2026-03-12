import hashlib

def hash_url(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def clean_text(text: str) -> str:
    return " ".join(text.split())
