from urllib.parse import urlparse

def same_domain(root: str, url: str) -> bool:
    return urlparse(root).netloc == urlparse(url).netloc

def normalize(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")
