from __future__ import annotations

import re
from collections import Counter
from typing import Optional
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

CTA_KEYWORDS = [
    "contato",
    "fale",
    "agende",
    "orcamento",
    "simule",
    "comprar",
    "saiba mais",
    "quero",
    "whatsapp",
]

FAQ_KEYWORDS = ["faq", "perguntas frequentes", "duvidas", "d\u00favidas"]
GALLERY_KEYWORDS = ["galeria", "gallery", "portfolio", "portifolio", "fotos", "imagens"]
TESTIMONIAL_KEYWORDS = ["depoimento", "testemunho", "avaliacoes", "avaliacoes", "clientes dizem"]
PRICING_KEYWORDS = ["r$", "preco", "precos", "investimento", "valor", "a partir de"]

REAL_ESTATE_KEYWORDS = [
    "lote",
    "lotes",
    "m2",
    "m\u00b2",
    "condominio",
    "empreendimento",
    "localizacao",
    "terreno",
    "residencial",
    "lancamento",
]

NUMBER_PATTERN = re.compile(r"\b\d+[.,]?\d*\b")


def _is_http_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys([item for item in items if item]))


def _clean_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.stripped_strings)


def _snippet(words: list[str], limit: int = 80) -> str:
    return " ".join(words[:limit]).strip()


def _extract_numbers(text: str, limit: int = 3) -> list[str]:
    matches = NUMBER_PATTERN.findall(text)
    return matches[:limit]


def _has_keyword(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _extract_nav_items(soup: BeautifulSoup) -> list[str]:
    items: list[str] = []

    def add_links(container):
        for a in container.find_all("a"):
            label = a.get_text(strip=True)
            if label and 2 <= len(label) <= 40:
                items.append(label)

    for nav in soup.find_all("nav"):
        add_links(nav)

    for nav in soup.find_all(attrs={"role": "navigation"}):
        add_links(nav)

    if not items:
        for header in soup.find_all(["header", "div", "section"]):
            class_id = " ".join(header.get("class", [])) + " " + (header.get("id") or "")
            key = class_id.lower()
            if any(token in key for token in ["nav", "menu", "navbar", "header", "topbar"]):
                add_links(header)

    if not items:
        counts: Counter[str] = Counter()
        for a in soup.find_all("a"):
            label = a.get_text(strip=True)
            if label and 2 <= len(label) <= 40:
                counts[label] += 1
        for label, _ in counts.most_common(8):
            items.append(label)

    return _unique(items)


def _extract_cta_texts(soup: BeautifulSoup) -> list[str]:
    texts: list[str] = []
    for tag in soup.find_all(["a", "button", "input"]):
        text = ""
        if tag.name == "input":
            if tag.get("type") in {"submit", "button"}:
                text = tag.get("value") or tag.get("aria-label") or ""
        else:
            text = tag.get_text(strip=True)
        if not text:
            continue
        lower = text.lower()
        if any(keyword in lower for keyword in CTA_KEYWORDS):
            texts.append(text)
    return _unique(texts)


def _extract_assets(soup: BeautifulSoup) -> list[str]:
    assets: list[str] = []
    for tag in soup.find_all(["img", "script", "link"]):
        src = tag.get("src") or tag.get("href")
        if src:
            assets.append(src)
    return assets


def _has_canonical(soup: BeautifulSoup) -> bool:
    for link in soup.find_all("link", rel=True):
        rel = link.get("rel")
        if isinstance(rel, list):
            rel_values = [value.lower() for value in rel]
        else:
            rel_values = str(rel).lower().split()
        if "canonical" in rel_values:
            return True
    return False


def _image_extension(url: str) -> Optional[str]:
    if not url:
        return None
    clean = url.split("?", 1)[0].split("#", 1)[0].lower()
    if "." not in clean:
        return None
    ext = clean.rsplit(".", 1)[-1]
    if ext in {"jpg", "jpeg", "png", "webp", "avif", "svg"}:
        return ext
    return None


def extract_basic(url: str, status: int, html: str) -> dict:
    soup = BeautifulSoup(html or "", "lxml")
    parsed = urlparse(url)
    domain = parsed.netloc

    title = soup.title.get_text(strip=True) if soup.title else None
    meta_desc = None
    md = soup.find("meta", attrs={"name": "description"})
    if md and md.get("content"):
        meta_desc = md["content"].strip()

    raw_links: list[str] = []
    internal_links: list[str] = []
    external_links: list[str] = []
    for a in soup.find_all("a"):
        href = a.get("href")
        if href and not href.startswith(("mailto:", "tel:", "#")):
            raw_links.append(href)
            abs_url = urljoin(url, href)
            if not _is_http_url(abs_url):
                continue
            if urlparse(abs_url).netloc == domain:
                internal_links.append(abs_url)
            else:
                external_links.append(abs_url)

    images = soup.find_all("img")
    images_total = len(images)
    images_missing_alt = sum(
        1 for img in images if not img.get("alt") or not img.get("alt").strip()
    )
    lazy_images = sum(
        1
        for img in images
        if img.get("loading") == "lazy" or img.get("data-src") or "lazy" in (img.get("class") or [])
    )
    lazy_loading_present = lazy_images > 0

    image_formats = Counter()
    for img in images:
        src = img.get("src") or img.get("data-src") or ""
        ext = _image_extension(src)
        if ext:
            image_formats[ext] += 1

    text = _clean_text(BeautifulSoup(html or "", "lxml"))
    words = text.split()
    word_count = len(words)
    text_snippet = _snippet(words)

    h1_tags = [h.get_text(strip=True) for h in soup.find_all("h1")]
    h2_tags = [h.get_text(strip=True) for h in soup.find_all("h2")]
    h3_tags = [h.get_text(strip=True) for h in soup.find_all("h3")]
    h1_text = h1_tags[0] if h1_tags else None

    section_count = len(soup.find_all("section"))
    heading_count = len(h1_tags) + len(h2_tags) + len(h3_tags)

    nav_items = _extract_nav_items(soup)
    cta_texts = _extract_cta_texts(soup)

    has_form = bool(soup.find("form"))
    has_video = bool(soup.find("video")) or bool(soup.find("iframe", src=re.compile("youtube|vimeo", re.I)))

    text_lower = text.lower()
    has_faq = _has_keyword(text_lower, FAQ_KEYWORDS)
    has_gallery = _has_keyword(text_lower, GALLERY_KEYWORDS)
    has_testimonials = _has_keyword(text_lower, TESTIMONIAL_KEYWORDS)
    has_pricing = _has_keyword(text_lower, PRICING_KEYWORDS)
    has_numbers = bool(NUMBER_PATTERN.search(text_lower))
    number_samples = _extract_numbers(text_lower)
    has_whatsapp = "whatsapp" in text_lower or "wa.me" in text_lower
    if not has_whatsapp:
        has_whatsapp = any("whatsapp" in link.lower() or "wa.me" in link.lower() for link in raw_links)
    is_real_estate = _has_keyword(text_lower, REAL_ESTATE_KEYWORDS)

    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    has_canonical = _has_canonical(soup)
    has_schema = bool(soup.find("script", attrs={"type": "application/ld+json"}))
    has_og = bool(soup.find("meta", attrs={"property": re.compile("^og:", re.I)}))

    robots_meta = None
    robots_tag = soup.find("meta", attrs={"name": "robots"})
    if robots_tag and robots_tag.get("content"):
        robots_meta = robots_tag["content"].strip().lower()

    indexable = None
    if robots_meta:
        indexable = not any(token in robots_meta for token in ["noindex", "none"])

    render_blocking_scripts = 0
    head = soup.find("head")
    if head:
        for script in head.find_all("script", src=True):
            if not script.get("async") and not script.get("defer"):
                render_blocking_scripts += 1

    assets = _extract_assets(soup)
    cdn_hints = any("cdn" in asset.lower() or "cloudflare" in asset.lower() or "cloudfront" in asset.lower() for asset in assets)

    page_size_kb = round(len((html or "").encode("utf-8")) / 1024, 1)

    internal_links = _unique(internal_links)
    external_links = _unique(external_links)

    return {
        "url": url,
        "status": status,
        "title": title,
        "h1_text": h1_text,
        "meta_description": meta_desc,
        "links_total": len(raw_links),
        "internal_links": internal_links,
        "external_links": external_links,
        "internal_links_count": len(internal_links),
        "external_links_count": len(external_links),
        "images_total": images_total,
        "images_missing_alt": images_missing_alt,
        "lazy_images_count": lazy_images,
        "lazy_loading_present": lazy_loading_present,
        "image_formats": dict(image_formats),
        "page_size_kb": page_size_kb,
        "render_blocking_scripts": render_blocking_scripts,
        "word_count": word_count,
        "text_snippet": text_snippet,
        "section_count": section_count,
        "heading_count": heading_count,
        "h1_count": len(h1_tags),
        "h2_count": len(h2_tags),
        "nav_items": nav_items,
        "cta_texts": cta_texts,
        "has_form": has_form,
        "has_video": has_video,
        "has_faq": has_faq,
        "has_gallery": has_gallery,
        "has_testimonials": has_testimonials,
        "has_pricing": has_pricing,
        "has_numbers": has_numbers,
        "number_samples": number_samples,
        "has_whatsapp": has_whatsapp,
        "is_real_estate": is_real_estate,
        "has_viewport": has_viewport,
        "has_canonical": has_canonical,
        "has_schema": has_schema,
        "has_og": has_og,
        "robots_meta": robots_meta,
        "indexable": indexable,
        "cdn_hints": cdn_hints,
        "domain": domain,
    }
