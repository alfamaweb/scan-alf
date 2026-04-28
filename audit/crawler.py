from __future__ import annotations

import ipaddress
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from .constants import (
    MAX_DEPTH,
    MAX_LINK_CHECKS,
    MAX_PAGES,
    MAX_RUNTIME_SECONDS,
    PER_PAGE_TIMEOUT_SECONDS,
    USER_AGENT,
)


def validate_url(raw_url: str) -> str:
    value = (raw_url or "").strip()
    if not value:
        raise ValueError("url is required")
    parsed = urlparse(value)
    if not parsed.scheme:
        parsed = urlparse(f"https://{value}")
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must start with http:// or https://")
    if not parsed.netloc:
        raise ValueError("invalid url")
    hostname = parsed.hostname or ""
    if hostname != "localhost":
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            if "." not in hostname:
                raise ValueError("invalid url host")
    normalized = urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            "",
            parsed.query,
            "",
        )
    )
    return normalized


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _is_http_url(url: str) -> bool:
    return url.startswith("http://") or url.startswith("https://")


def _same_origin(url: str, origin: str) -> bool:
    a = urlparse(url)
    b = urlparse(origin)
    return a.scheme == b.scheme and a.netloc == b.netloc


def _norm_link(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path or "/",
            "",
            parsed.query,
            "",
        )
    )


def _extract_internal_links(soup: BeautifulSoup, base_url: str, origin: str) -> list[str]:
    found: list[str] = []
    for tag in soup.find_all("a", href=True):
        href = (tag.get("href") or "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = urldefrag(urljoin(base_url, href))[0]
        if not _is_http_url(absolute):
            continue
        if _same_origin(absolute, origin):
            found.append(_norm_link(absolute))
    return list(dict.fromkeys(found))


def _get_title(soup: BeautifulSoup) -> str:
    tag = soup.find("title")
    if not tag:
        return ""
    return " ".join(tag.get_text(" ", strip=True).split())


def _get_meta_description(soup: BeautifulSoup) -> str:
    tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    if not tag:
        return ""
    value = (tag.get("content") or "").strip()
    return " ".join(value.split())


def _get_canonical(soup: BeautifulSoup, page_url: str) -> str:
    for tag in soup.find_all("link", href=True):
        rel = tag.get("rel") or []
        rel_values = [str(v).lower() for v in rel] if isinstance(rel, list) else [str(rel).lower()]
        if "canonical" in rel_values:
            return _norm_link(urljoin(page_url, str(tag.get("href"))))
    return ""


def _get_robots_meta(soup: BeautifulSoup) -> str:
    directives: set[str] = set()
    for name in ("robots", "googlebot"):
        tag = soup.find("meta", attrs={"name": re.compile(rf"^{name}$", re.I)})
        if tag:
            content = str(tag.get("content") or "").strip().lower()
            directives.update(d.strip() for d in content.split(",") if d.strip())
    if "none" in directives:
        directives.discard("none")
        directives.update({"noindex", "nofollow"})
    return ", ".join(sorted(directives))


def _count_inputs_without_labels(soup: BeautifulSoup) -> int:
    labels_for = {
        (label.get("for") or "").strip()
        for label in soup.find_all("label", attrs={"for": True})
        if (label.get("for") or "").strip()
    }
    missing = 0
    for inp in soup.find_all("input"):
        input_type = (inp.get("type") or "text").strip().lower()
        if input_type in {"hidden", "submit", "button", "image", "reset"}:
            continue
        has_aria = bool((inp.get("aria-label") or "").strip()) or bool(
            (inp.get("aria-labelledby") or "").strip()
        )
        input_id = (inp.get("id") or "").strip()
        has_for_label = bool(input_id and input_id in labels_for)
        has_wrapping_label = inp.find_parent("label") is not None
        if not (has_aria or has_for_label or has_wrapping_label):
            missing += 1
    return missing


def _count_render_blocking(soup: BeautifulSoup) -> int:
    count = 0
    head = soup.find("head")
    if not head:
        return 0
    for script in head.find_all("script", src=True):
        if not script.get("async") and not script.get("defer"):
            count += 1
    for link in head.find_all("link", href=True):
        rel = link.get("rel") or []
        rel_values = [str(v).lower() for v in rel] if isinstance(rel, list) else [str(rel).lower()]
        if "stylesheet" in rel_values:
            count += 1
    return count


def _collect_resource_urls(soup: BeautifulSoup, page_url: str) -> list[str]:
    urls: list[str] = []
    for tag in soup.find_all(["script", "img", "iframe", "source"]):
        src = (tag.get("src") or tag.get("data-src") or "").strip()
        if src:
            urls.append(urljoin(page_url, src))
    for tag in soup.find_all("link", href=True):
        href = (tag.get("href") or "").strip()
        if href:
            urls.append(urljoin(page_url, href))
    return urls


def _parse_html_page(url: str, status: int, response: httpx.Response, origin: str) -> dict[str, Any]:
    content_type = str(response.headers.get("content-type", "")).lower()
    is_html = "text/html" in content_type
    ttfb_ms = int((response.elapsed.total_seconds() if response.elapsed else 0) * 1000)
    page: dict[str, Any] = {
        "url": _norm_link(url),
        "final_url": _norm_link(str(response.url)),
        "status": status,
        "is_html": is_html,
        "content_type": content_type,
        "ttfb_ms": ttfb_ms,
        "html_size_bytes": len(response.content or b""),
        "redirect_hops": len(response.history),
        "internal_links": [],
        "title": "",
        "meta_description": "",
        "canonical": "",
        "robots_meta": "",
        "h1_count": 0,
        "lang": "",
        "images_total": 0,
        "images_missing_alt": 0,
        "inputs_total": 0,
        "inputs_missing_label": 0,
        "resource_count": 0,
        "render_blocking_count": 0,
        "mixed_content_count": 0,
        "word_count": 0,
    }
    if not is_html:
        return page

    soup = BeautifulSoup(response.text or "", "html.parser")
    title = _get_title(soup)
    meta_description = _get_meta_description(soup)
    canonical = _get_canonical(soup, page["final_url"])
    robots_meta = _get_robots_meta(soup)
    x_robots = str(response.headers.get("x-robots-tag", "")).strip().lower()
    if x_robots:
        directives = set(robots_meta.split(", ")) | {d.strip() for d in x_robots.split(",") if d.strip()}
        robots_meta = ", ".join(sorted(d for d in directives if d))
    h1_count = len(soup.find_all("h1"))

    html_tag = soup.find("html")
    lang = (html_tag.get("lang") or "").strip().lower() if html_tag else ""

    images = soup.find_all("img")
    images_total = len(images)
    images_missing_alt = sum(1 for img in images if not (img.get("alt") or "").strip())

    inputs_total = len(soup.find_all("input"))
    inputs_missing_label = _count_inputs_without_labels(soup)

    resources = _collect_resource_urls(soup, page["final_url"])
    resource_count = len(resources)
    render_blocking_count = _count_render_blocking(soup)

    mixed_content_count = 0
    if urlparse(page["final_url"]).scheme == "https":
        mixed_content_count = sum(1 for ref in resources if str(ref).lower().startswith("http://"))

    for tag in soup(["script", "style", "noscript"]):
        tag.extract()
    page_text = " ".join(soup.get_text(" ", strip=True).split())
    word_count = len(page_text.split()) if page_text else 0

    page.update(
        {
            "internal_links": _extract_internal_links(soup, page["final_url"], origin),
            "title": title,
            "meta_description": meta_description,
            "canonical": canonical,
            "robots_meta": robots_meta,
            "h1_count": h1_count,
            "lang": lang,
            "images_total": images_total,
            "images_missing_alt": images_missing_alt,
            "inputs_total": inputs_total,
            "inputs_missing_label": inputs_missing_label,
            "resource_count": resource_count,
            "render_blocking_count": render_blocking_count,
            "mixed_content_count": mixed_content_count,
            "word_count": word_count,
        }
    )
    return page


def _fetch_robots_and_sitemap(
    client: httpx.Client,
    start_url: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    parsed = urlparse(start_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    robots_url = f"{origin}/robots.txt"
    sitemap_url = f"{origin}/sitemap.xml"
    parser: RobotFileParser | None = None
    robots_present = False
    robots_status = None
    robots_text = ""

    try:
        robots_response = client.get(robots_url, timeout=timeout_seconds)
        robots_status = robots_response.status_code
        robots_text = robots_response.text or ""
        if robots_response.status_code == 200:
            robots_present = True
            parser = RobotFileParser()
            parser.parse(robots_text.splitlines())
    except Exception:
        robots_status = None

    sitemap_present = "sitemap:" in robots_text.lower()
    if not sitemap_present:
        try:
            sitemap_response = client.get(sitemap_url, timeout=timeout_seconds)
            if sitemap_response.status_code == 200:
                sitemap_present = True
        except Exception:
            sitemap_present = False

    crawl_blocked = False
    if parser is not None:
        crawl_blocked = (
            not parser.can_fetch("*", start_url)
            or not parser.can_fetch("Googlebot", start_url)
        )

    return {
        "robots_url": robots_url,
        "robots_present": robots_present,
        "robots_status": robots_status,
        "sitemap_url": sitemap_url,
        "sitemap_present": sitemap_present,
        "robot_parser": parser,
        "crawl_blocked": crawl_blocked,
    }


def crawl_site(
    start_url: str,
    *,
    max_pages: int = MAX_PAGES,
    max_depth: int = MAX_DEPTH,
    max_runtime_seconds: int = MAX_RUNTIME_SECONDS,
    max_link_checks: int = MAX_LINK_CHECKS,
    per_page_timeout_seconds: int = PER_PAGE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    started_at = time.monotonic()
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    queued = {start_url}
    visited = set()
    pages: list[dict[str, Any]] = []
    status_cache: dict[str, int] = {}
    all_internal_links: set[str] = set()
    skipped_by_robots = 0
    non_html_urls = 0
    fetch_errors: list[dict[str, Any]] = []
    limit_notes: list[str] = []
    origin = start_url
    ssl_error_detected = False

    verify_ssl: bool | str = True
    try:
        with httpx.Client(follow_redirects=True, headers={"User-Agent": USER_AGENT}, timeout=per_page_timeout_seconds) as _probe:
            _probe.get(start_url, timeout=per_page_timeout_seconds)
    except httpx.ConnectError:
        verify_ssl = False
        ssl_error_detected = True
    except Exception:
        pass

    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=per_page_timeout_seconds,
        verify=verify_ssl,
    ) as client:
        robots_info = _fetch_robots_and_sitemap(client, start_url, per_page_timeout_seconds)
        robot_parser: RobotFileParser | None = robots_info["robot_parser"]

        while queue:
            elapsed = time.monotonic() - started_at
            if elapsed >= max_runtime_seconds:
                if "MAX_RUNTIME_SECONDS reached during crawl." not in limit_notes:
                    limit_notes.append("MAX_RUNTIME_SECONDS reached during crawl.")
                break
            if len(pages) >= max_pages:
                if "MAX_PAGES reached." not in limit_notes:
                    limit_notes.append("MAX_PAGES reached.")
                break

            current_url, depth = queue.popleft()
            queued.discard(current_url)
            if current_url in visited:
                continue
            visited.add(current_url)
            if depth > max_depth:
                continue
            if robot_parser and not robot_parser.can_fetch(USER_AGENT, current_url):
                skipped_by_robots += 1
                continue

            try:
                response = client.get(current_url, timeout=per_page_timeout_seconds)
                page = _parse_html_page(current_url, response.status_code, response, origin)
                page["depth"] = depth
            except Exception as exc:
                page = {
                    "url": _norm_link(current_url),
                    "final_url": _norm_link(current_url),
                    "status": 0,
                    "is_html": False,
                    "content_type": "",
                    "ttfb_ms": 0,
                    "html_size_bytes": 0,
                    "redirect_hops": 0,
                    "internal_links": [],
                    "title": "",
                    "meta_description": "",
                    "canonical": "",
                    "robots_meta": "",
                    "h1_count": 0,
                    "lang": "",
                    "images_total": 0,
                    "images_missing_alt": 0,
                    "inputs_total": 0,
                    "inputs_missing_label": 0,
                    "resource_count": 0,
                    "render_blocking_count": 0,
                    "mixed_content_count": 0,
                    "word_count": 0,
                    "depth": depth,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                fetch_errors.append({"url": current_url, "error": page["error"]})

            status_cache[page["url"]] = int(page["status"])
            status_cache[page["final_url"]] = int(page["status"])

            if page["is_html"]:
                pages.append(page)
                for link in page["internal_links"]:
                    all_internal_links.add(link)
                    if depth < max_depth and link not in visited and link not in queued:
                        queued.add(link)
                        queue.append((link, depth + 1))
            else:
                non_html_urls += 1

        broken_internal_links: list[dict[str, Any]] = []
        links_checked = 0
        if max_link_checks > 0:
            for link in sorted(all_internal_links):
                if links_checked >= max_link_checks:
                    if "MAX_LINK_CHECKS reached while checking internal links." not in limit_notes:
                        limit_notes.append("MAX_LINK_CHECKS reached while checking internal links.")
                    break
                if (time.monotonic() - started_at) >= max_runtime_seconds:
                    if "MAX_RUNTIME_SECONDS reached while checking internal links." not in limit_notes:
                        limit_notes.append("MAX_RUNTIME_SECONDS reached while checking internal links.")
                    break
                if robot_parser and not robot_parser.can_fetch(USER_AGENT, link):
                    continue

                links_checked += 1
                status = status_cache.get(link)
                if status is None:
                    try:
                        head = client.head(link, timeout=per_page_timeout_seconds, follow_redirects=True)
                        status = head.status_code
                        if status in {405, 501}:
                            get_resp = client.get(link, timeout=per_page_timeout_seconds, follow_redirects=True)
                            status = get_resp.status_code
                    except Exception:
                        status = 0
                    status_cache[link] = status

                if status >= 400 or status == 0:
                    broken_internal_links.append({"url": link, "status": status})

    return {
        "url": start_url,
        "generated_at": _now_iso(),
        "pages": pages,
        "status_cache": status_cache,
        "broken_internal_links": broken_internal_links,
        "links_checked": links_checked,
        "all_internal_links_count": len(all_internal_links),
        "skipped_by_robots": skipped_by_robots,
        "non_html_urls": non_html_urls,
        "fetch_errors": fetch_errors,
        "robots": robots_info,
        "limit_notes": limit_notes,
        "runtime_seconds": round(time.monotonic() - started_at, 2),
        "ssl_error_detected": ssl_error_detected,
    }
