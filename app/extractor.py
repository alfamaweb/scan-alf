from __future__ import annotations
from bs4 import BeautifulSoup
from urllib.parse import urlparse


def extract_basic(url: str, status: int, html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else None

    meta_desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()

    links_total = len(soup.find_all("a"))

    images_missing_alt = 0
    for img in soup.find_all("img"):
        alt = img.get("alt")
        if alt is None or alt.strip() == "":
            images_missing_alt += 1

    return {
        "url": url,
        "status": status,
        "title": title,
        "meta_description": meta_desc,
        "links_total": links_total,
        "images_missing_alt": images_missing_alt,
        "domain": urlparse(url).netloc,
    }
