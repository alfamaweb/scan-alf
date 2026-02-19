from __future__ import annotations

import ipaddress
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

MAX_PAGES = 150
MAX_DEPTH = 6
MAX_RUNTIME_SECONDS = 120
PER_PAGE_TIMEOUT_SECONDS = 20
MAX_LINK_CHECKS = 400
USER_AGENT = "SimpleSiteAuditBot/1.0"

SUMMARY_MAX_PAGES = 12
SUMMARY_MAX_DEPTH = 1
SUMMARY_MAX_RUNTIME_SECONDS = 8
SUMMARY_MAX_LINK_CHECKS = 0
SUMMARY_PER_PAGE_TIMEOUT_SECONDS = 5
SUMMARY_CACHE_TTL_SECONDS = 600
AUDIT_CACHE_TTL_SECONDS = 900

SEVERITY_ORDER = {"critical": 4, "high": 3, "medium": 2, "low": 1}
SEVERITY_PENALTY = {"critical": 35, "high": 20, "medium": 10, "low": 4}

SECTION_KEYS = [
    "overall",
    "seo",
    "a11y",
    "content",
    "performance",
    "indexacao",
    "erros_criticos",
]

_SUMMARY_CACHE: dict[str, tuple[float, dict[str, str]]] = {}
_AUDIT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class LLMUnavailableError(RuntimeError):
    pass


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
    tag = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    if not tag:
        return ""
    return str(tag.get("content") or "").strip().lower()


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
    h1_count = len(soup.find_all("h1"))

    html_tag = soup.find("html")
    lang = (html_tag.get("lang") or "").strip().lower() if html_tag else ""

    images = soup.find_all("img")
    images_total = len(images)
    images_missing_alt = sum(
        1 for img in images if not (img.get("alt") or "").strip()
    )

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

    return {
        "robots_url": robots_url,
        "robots_present": robots_present,
        "robots_status": robots_status,
        "sitemap_url": sitemap_url,
        "sitemap_present": sitemap_present,
        "robot_parser": parser,
    }


def _crawl_site(
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

    with httpx.Client(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=per_page_timeout_seconds,
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
    }


def _make_evidence(
    url: str,
    selector: str | None = None,
    value: Any | None = None,
    metric: Any | None = None,
) -> dict[str, Any]:
    return {
        "url": url,
        "selector": selector,
        "value": value,
        "metric": metric,
    }


def _make_finding(
    finding_id: str,
    severity: str,
    title: str,
    description: str,
    impact: str,
    how_to_fix: str,
    evidence: list[dict[str, Any]] | None = None,
    affected_urls: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "severity": severity,
        "title": title,
        "description": description,
        "impact": impact,
        "how_to_fix": how_to_fix,
        "evidence": evidence or [],
        "affected_urls": affected_urls or [],
    }


def _sorted_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        findings,
        key=lambda f: (
            -SEVERITY_ORDER.get(str(f.get("severity")), 0),
            str(f.get("title", "")).lower(),
        ),
    )


def _build_section(summary: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = _sorted_findings(findings)[:10]
    score = 100
    for finding in ordered:
        score -= SEVERITY_PENALTY.get(str(finding.get("severity")), 0)
    score = max(0, int(score))

    has_critical = any(str(f.get("severity")) == "critical" for f in ordered)
    if has_critical or score < 60:
        status = "critical"
    elif score < 85:
        status = "attention"
    else:
        status = "ok"

    next_actions: list[str] = []
    for finding in ordered:
        action = str(finding.get("how_to_fix") or "").strip()
        if action and action not in next_actions:
            next_actions.append(action)
        if len(next_actions) >= 5:
            break

    if not next_actions:
        next_actions = ["Manter monitoramento recorrente e validar regressao semanal."]

    return {
        "score": score,
        "status": status,
        "summary": summary,
        "findings": ordered,
        "next_actions": next_actions[:5],
    }


def _count_by_predicate(pages: list[dict[str, Any]], predicate) -> list[dict[str, Any]]:
    return [page for page in pages if predicate(page)]


def _top_urls(pages: list[dict[str, Any]], limit: int = 25) -> list[str]:
    return [str(page.get("url")) for page in pages[:limit]]


def _build_sections(
    crawl: dict[str, Any],
    *,
    include_limit_findings: bool = True,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    pages = crawl["pages"]
    broken_links = crawl["broken_internal_links"]
    robots = crawl["robots"]
    limit_notes = crawl["limit_notes"]

    title_missing = _count_by_predicate(pages, lambda p: not p["title"])
    title_len_bad = _count_by_predicate(
        pages, lambda p: p["title"] and (len(p["title"]) < 15 or len(p["title"]) > 60)
    )
    meta_missing = _count_by_predicate(pages, lambda p: not p["meta_description"])
    meta_len_bad = _count_by_predicate(
        pages,
        lambda p: p["meta_description"]
        and (len(p["meta_description"]) < 70 or len(p["meta_description"]) > 160),
    )
    canonical_missing = _count_by_predicate(pages, lambda p: not p["canonical"])
    h1_bad = _count_by_predicate(pages, lambda p: int(p["h1_count"]) != 1)

    noindex_pages = _count_by_predicate(
        pages, lambda p: "noindex" in str(p["robots_meta"] or "").lower()
    )
    canonical_conflicts = _count_by_predicate(
        pages,
        lambda p: bool(p["canonical"]) and not _same_origin(str(p["canonical"]), crawl["url"]),
    )

    missing_lang = _count_by_predicate(pages, lambda p: not p["lang"])
    missing_alt_pages = _count_by_predicate(pages, lambda p: int(p["images_missing_alt"]) > 0)
    missing_label_pages = _count_by_predicate(pages, lambda p: int(p["inputs_missing_label"]) > 0)

    thin_content = _count_by_predicate(pages, lambda p: int(p["word_count"]) < 120)
    low_heading_structure = _count_by_predicate(pages, lambda p: int(p["h1_count"]) == 0)

    slow_pages = _count_by_predicate(pages, lambda p: int(p["ttfb_ms"]) > 1200)
    heavy_html = _count_by_predicate(pages, lambda p: int(p["html_size_bytes"]) > 512_000)
    high_request_pages = _count_by_predicate(pages, lambda p: int(p["resource_count"]) > 80)
    render_blocking = _count_by_predicate(pages, lambda p: int(p["render_blocking_count"]) > 5)

    http_error_pages = _count_by_predicate(pages, lambda p: int(p["status"]) >= 400 or int(p["status"]) == 0)
    redirect_chain_pages = _count_by_predicate(pages, lambda p: int(p["redirect_hops"]) >= 3)
    mixed_content_pages = _count_by_predicate(pages, lambda p: int(p["mixed_content_count"]) > 0)

    seo_findings: list[dict[str, Any]] = []
    a11y_findings: list[dict[str, Any]] = []
    content_findings: list[dict[str, Any]] = []
    performance_findings: list[dict[str, Any]] = []
    indexacao_findings: list[dict[str, Any]] = []
    critical_findings: list[dict[str, Any]] = []

    if title_missing:
        seo_findings.append(
            _make_finding(
                "seo_title_missing",
                "high",
                "Paginas sem title",
                f"{len(title_missing)} paginas HTML sem tag <title>.",
                "Prejudica relevancia organica e CTR.",
                "Definir um title unico e descritivo por pagina.",
                [
                    _make_evidence(
                        title_missing[0]["url"],
                        selector="title",
                        value="",
                        metric=len(title_missing),
                    )
                ],
                _top_urls(title_missing),
            )
        )

    if title_len_bad:
        seo_findings.append(
            _make_finding(
                "seo_title_length",
                "medium",
                "Titles fora do tamanho recomendado",
                f"{len(title_len_bad)} paginas com title curto ou longo demais.",
                "Pode reduzir clareza do snippet no buscador.",
                "Manter titles entre 15 e 60 caracteres.",
                [_make_evidence(title_len_bad[0]["url"], selector="title", metric=len(title_len_bad))],
                _top_urls(title_len_bad),
            )
        )

    if meta_missing:
        seo_findings.append(
            _make_finding(
                "seo_meta_description_missing",
                "medium",
                "Meta description ausente",
                f"{len(meta_missing)} paginas sem meta description.",
                "Diminui controle sobre texto exibido no resultado de busca.",
                "Adicionar meta description unica e objetiva em cada pagina.",
                [
                    _make_evidence(
                        meta_missing[0]["url"],
                        selector='meta[name="description"]',
                        value="",
                        metric=len(meta_missing),
                    )
                ],
                _top_urls(meta_missing),
            )
        )

    if meta_len_bad:
        seo_findings.append(
            _make_finding(
                "seo_meta_description_length",
                "low",
                "Meta descriptions fora do tamanho recomendado",
                f"{len(meta_len_bad)} paginas com meta description curta ou longa demais.",
                "Pode afetar compreensao do snippet.",
                "Ajustar meta descriptions para faixa entre 70 e 160 caracteres.",
                [_make_evidence(meta_len_bad[0]["url"], selector='meta[name="description"]')],
                _top_urls(meta_len_bad),
            )
        )

    if canonical_missing:
        seo_findings.append(
            _make_finding(
                "seo_canonical_missing",
                "medium",
                "Canonical ausente",
                f"{len(canonical_missing)} paginas sem link canonical.",
                "Pode dificultar consolidacao de sinais para URLs similares.",
                "Adicionar <link rel='canonical'> em paginas indexaveis.",
                [_make_evidence(canonical_missing[0]["url"], selector="link[rel=canonical]")],
                _top_urls(canonical_missing),
            )
        )

    if h1_bad:
        seo_findings.append(
            _make_finding(
                "seo_h1_count",
                "medium",
                "Estrutura de H1 inconsistente",
                f"{len(h1_bad)} paginas com quantidade de H1 diferente de 1.",
                "Pode reduzir clareza semantica da pagina.",
                "Garantir exatamente um H1 principal por pagina.",
                [_make_evidence(h1_bad[0]["url"], selector="h1", metric=len(h1_bad))],
                _top_urls(h1_bad),
            )
        )

    if broken_links:
        severity = "critical" if len(broken_links) >= 10 else "high"
        seo_findings.append(
            _make_finding(
                "seo_broken_internal_links",
                severity,
                "Links internos quebrados",
                f"{len(broken_links)} links internos retornando erro (4xx/5xx/timeout).",
                "Impacta rastreabilidade, UX e distribuicao de autoridade interna.",
                "Corrigir URLs quebradas e atualizar links de navegacao.",
                [
                    _make_evidence(
                        broken_links[0]["url"],
                        metric=broken_links[0]["status"],
                    )
                ],
                [item["url"] for item in broken_links[:25]],
            )
        )

    if missing_alt_pages:
        total_missing_alt = sum(int(page["images_missing_alt"]) for page in missing_alt_pages)
        severity = "high" if total_missing_alt >= 20 else "medium"
        a11y_findings.append(
            _make_finding(
                "a11y_img_alt_missing",
                severity,
                "Imagens sem texto alternativo",
                f"{total_missing_alt} imagens sem alt em {len(missing_alt_pages)} paginas.",
                "Prejudica acessibilidade para leitores de tela.",
                "Definir atributo alt descritivo em todas as imagens relevantes.",
                [
                    _make_evidence(
                        missing_alt_pages[0]["url"],
                        selector="img[alt]",
                        metric=total_missing_alt,
                    )
                ],
                _top_urls(missing_alt_pages),
            )
        )

    if missing_label_pages:
        total_missing_label = sum(int(page["inputs_missing_label"]) for page in missing_label_pages)
        a11y_findings.append(
            _make_finding(
                "a11y_input_label_missing",
                "high",
                "Campos de formulario sem label",
                f"{total_missing_label} inputs sem label associada.",
                "Dificulta navegacao com tecnologia assistiva.",
                "Associar labels via for/id ou usar aria-label/aria-labelledby.",
                [
                    _make_evidence(
                        missing_label_pages[0]["url"],
                        selector="input",
                        metric=total_missing_label,
                    )
                ],
                _top_urls(missing_label_pages),
            )
        )

    if missing_lang:
        a11y_findings.append(
            _make_finding(
                "a11y_lang_missing",
                "medium",
                "Atributo lang ausente",
                f"{len(missing_lang)} paginas sem atributo lang na tag html.",
                "Pode reduzir compatibilidade com leitores de tela.",
                "Definir lang apropriado no elemento <html>.",
                [_make_evidence(missing_lang[0]["url"], selector="html[lang]")],
                _top_urls(missing_lang),
            )
        )

    if title_missing:
        a11y_findings.append(
            _make_finding(
                "a11y_title_missing",
                "medium",
                "Titulo da pagina ausente",
                f"{len(title_missing)} paginas sem titulo de documento.",
                "Compromete contexto de navegacao para usuarios assistivos.",
                "Adicionar tag <title> descritiva em todas as paginas.",
                [_make_evidence(title_missing[0]["url"], selector="title")],
                _top_urls(title_missing),
            )
        )

    if thin_content:
        content_findings.append(
            _make_finding(
                "content_thin_pages",
                "medium",
                "Conteudo muito curto",
                f"{len(thin_content)} paginas com menos de 120 palavras.",
                "Pode reduzir capacidade de ranqueamento e conversao.",
                "Expandir conteudo util com contexto, prova e CTA claros.",
                [_make_evidence(thin_content[0]["url"], metric=thin_content[0]["word_count"])],
                _top_urls(thin_content),
            )
        )

    if low_heading_structure:
        content_findings.append(
            _make_finding(
                "content_missing_h1",
                "medium",
                "Estrutura sem heading principal",
                f"{len(low_heading_structure)} paginas sem H1.",
                "Reduz clareza da proposta principal para usuarios e buscadores.",
                "Incluir heading principal alinhado com o objetivo da pagina.",
                [_make_evidence(low_heading_structure[0]["url"], selector="h1")],
                _top_urls(low_heading_structure),
            )
        )

    if slow_pages:
        performance_findings.append(
            _make_finding(
                "perf_slow_ttfb",
                "high",
                "TTFB elevado",
                f"{len(slow_pages)} paginas com TTFB acima de 1200ms.",
                "Aumenta tempo de carregamento percebido.",
                "Revisar backend, cache e latencia de servidor.",
                [_make_evidence(slow_pages[0]["url"], metric=slow_pages[0]["ttfb_ms"])],
                _top_urls(slow_pages),
            )
        )

    if heavy_html:
        performance_findings.append(
            _make_finding(
                "perf_heavy_html",
                "medium",
                "HTML muito pesado",
                f"{len(heavy_html)} paginas com HTML acima de 500KB.",
                "Pode aumentar tempo de download e parse.",
                "Reduzir markup redundante e componentes inline excessivos.",
                [_make_evidence(heavy_html[0]["url"], metric=heavy_html[0]["html_size_bytes"])],
                _top_urls(heavy_html),
            )
        )

    if high_request_pages:
        performance_findings.append(
            _make_finding(
                "perf_many_requests",
                "medium",
                "Muitos recursos na pagina",
                f"{len(high_request_pages)} paginas com mais de 80 recursos referenciados.",
                "Aumenta custo de renderizacao e transferencias.",
                "Consolidar e otimizar scripts, CSS e imagens.",
                [_make_evidence(high_request_pages[0]["url"], metric=high_request_pages[0]["resource_count"])],
                _top_urls(high_request_pages),
            )
        )

    if render_blocking:
        performance_findings.append(
            _make_finding(
                "perf_render_blocking",
                "medium",
                "Recursos bloqueando renderizacao",
                f"{len(render_blocking)} paginas com mais de 5 recursos bloqueantes no head.",
                "Pode atrasar exibicao de conteudo acima da dobra.",
                "Aplicar defer/async em scripts e otimizar CSS critico.",
                [
                    _make_evidence(
                        render_blocking[0]["url"],
                        metric=render_blocking[0]["render_blocking_count"],
                    )
                ],
                _top_urls(render_blocking),
            )
        )

    if not robots["robots_present"]:
        indexacao_findings.append(
            _make_finding(
                "indexacao_robots_missing",
                "high",
                "robots.txt ausente",
                "Arquivo robots.txt nao encontrado com status 200.",
                "Bots podem rastrear caminhos sem orientacao.",
                "Publicar robots.txt com regras claras de rastreamento.",
                [_make_evidence(robots["robots_url"], metric=robots["robots_status"])],
                [robots["robots_url"]],
            )
        )

    if not robots["sitemap_present"]:
        indexacao_findings.append(
            _make_finding(
                "indexacao_sitemap_missing",
                "medium",
                "Sitemap nao encontrado",
                "Sitemap nao encontrado em robots.txt nem em /sitemap.xml.",
                "Pode dificultar descoberta de URLs relevantes.",
                "Gerar sitemap.xml atualizado e referenciar no robots.txt.",
                [_make_evidence(robots["sitemap_url"])],
                [robots["sitemap_url"]],
            )
        )

    if noindex_pages:
        indexacao_findings.append(
            _make_finding(
                "indexacao_noindex_pages",
                "medium",
                "Paginas com noindex",
                f"{len(noindex_pages)} paginas HTML com meta robots noindex.",
                "Pode remover paginas da indexacao organica.",
                "Revisar noindex e manter apenas em paginas que realmente devem ficar fora do indice.",
                [_make_evidence(noindex_pages[0]["url"], selector='meta[name="robots"]')],
                _top_urls(noindex_pages),
            )
        )

    if canonical_conflicts:
        indexacao_findings.append(
            _make_finding(
                "indexacao_canonical_conflict",
                "high",
                "Canonical apontando para outra origem",
                f"{len(canonical_conflicts)} paginas com canonical em dominio diferente.",
                "Pode transferir sinais de relevancia para outro host.",
                "Ajustar canonical para URL canonica correta do mesmo site.",
                [_make_evidence(canonical_conflicts[0]["url"], value=canonical_conflicts[0]["canonical"])],
                _top_urls(canonical_conflicts),
            )
        )

    if http_error_pages:
        sev = "critical" if any(int(page["status"]) >= 500 for page in http_error_pages) else "high"
        critical_findings.append(
            _make_finding(
                "critical_http_errors",
                sev,
                "Paginas com erro HTTP",
                f"{len(http_error_pages)} paginas HTML com status 4xx/5xx ou timeout.",
                "Interrompe jornada do usuario e rastreio.",
                "Corrigir rotas quebradas e falhas de servidor prioritariamente.",
                [_make_evidence(http_error_pages[0]["url"], metric=http_error_pages[0]["status"])],
                _top_urls(http_error_pages),
            )
        )

    if redirect_chain_pages:
        critical_findings.append(
            _make_finding(
                "critical_redirect_chains",
                "high",
                "Cadeias de redirecionamento longas",
                f"{len(redirect_chain_pages)} paginas com cadeia de 3+ redirecionamentos.",
                "Aumenta latencia e pode causar perda de sinal SEO.",
                "Reduzir para no maximo um redirecionamento por URL.",
                [_make_evidence(redirect_chain_pages[0]["url"], metric=redirect_chain_pages[0]["redirect_hops"])],
                _top_urls(redirect_chain_pages),
            )
        )

    if mixed_content_pages:
        critical_findings.append(
            _make_finding(
                "critical_mixed_content",
                "high",
                "Mixed content em paginas HTTPS",
                f"{len(mixed_content_pages)} paginas carregando recursos HTTP em contexto HTTPS.",
                "Pode causar bloqueio de recursos e alertas de seguranca.",
                "Migrar todos os recursos para HTTPS.",
                [_make_evidence(mixed_content_pages[0]["url"], metric=mixed_content_pages[0]["mixed_content_count"])],
                _top_urls(mixed_content_pages),
            )
        )

    if include_limit_findings and limit_notes:
        note_text = "; ".join(limit_notes)
        partial_finding = _make_finding(
            "critical_partial_crawl",
            "critical",
            "Crawl parcial por limite de seguranca",
            f"A varredura foi interrompida antes de cobrir todo o site: {note_text}",
            "Resultados representam amostra parcial do site.",
            "Reexecutar auditoria apos reduzir complexidade de rastreamento ou revisar arquitetura.",
            [_make_evidence(crawl["url"], metric=note_text)],
            [crawl["url"]],
        )
        critical_findings.append(partial_finding)

    seo_summary = (
        f"{len(seo_findings)} achados SEO em {len(pages)} paginas HTML analisadas."
        if pages
        else "Nenhuma pagina HTML analisada para SEO."
    )
    a11y_summary = (
        f"{len(a11y_findings)} achados de acessibilidade em verificacoes basicas."
        if pages
        else "Nenhuma pagina HTML analisada para acessibilidade."
    )
    content_summary = (
        f"{len(content_findings)} achados de conteudo com foco em cobertura e estrutura."
        if pages
        else "Nenhuma pagina HTML analisada para conteudo."
    )
    performance_summary = (
        f"{len(performance_findings)} achados de performance por proxies leves (TTFB, tamanho HTML e recursos)."
        if pages
        else "Nenhuma pagina HTML analisada para performance."
    )
    indexacao_summary = (
        f"{len(indexacao_findings)} achados de indexacao com base em robots, sitemap, noindex e canonical."
        if pages
        else "Nenhuma pagina HTML analisada para indexacao."
    )
    critical_summary = (
        f"{len(critical_findings)} achados criticos relacionados a erro HTTP, redirect chain, mixed content e limites."
        if pages or critical_findings
        else "Nenhum erro critico identificado."
    )

    seo_section = _build_section(seo_summary, seo_findings)
    a11y_section = _build_section(a11y_summary, a11y_findings)
    content_section = _build_section(content_summary, content_findings)
    performance_section = _build_section(performance_summary, performance_findings)
    indexacao_section = _build_section(indexacao_summary, indexacao_findings)
    critical_section = _build_section(critical_summary, critical_findings)

    all_findings = (
        seo_section["findings"]
        + a11y_section["findings"]
        + content_section["findings"]
        + performance_section["findings"]
        + indexacao_section["findings"]
        + critical_section["findings"]
    )
    overall_summary = (
        f"Crawl em {len(pages)} paginas HTML; {len(all_findings)} achados relevantes."
        if pages
        else "Nenhuma pagina HTML rastreada. Verifique disponibilidade e robots."
    )
    overall_section = _build_section(overall_summary, all_findings)
    if pages:
        category_avg = int(
            (
                seo_section["score"]
                + a11y_section["score"]
                + content_section["score"]
                + performance_section["score"]
                + indexacao_section["score"]
                + critical_section["score"]
            )
            / 6
        )
        overall_section["score"] = category_avg
        if category_avg < 60 or any(f["severity"] == "critical" for f in overall_section["findings"]):
            overall_section["status"] = "critical"
        elif category_avg < 85:
            overall_section["status"] = "attention"
        else:
            overall_section["status"] = "ok"

    sections = {
        "overall": overall_section,
        "seo": seo_section,
        "a11y": a11y_section,
        "content": content_section,
        "performance": performance_section,
        "indexacao": indexacao_section,
        "erros_criticos": critical_section,
    }

    for key, measured in {
        "overall": [
            "Cobertura do crawl HTML",
            "Consolidacao de achados por severidade",
            "Status geral por score medio das categorias",
        ],
        "seo": [
            "title e meta description",
            "canonical e h1",
            "links internos quebrados",
            "sitemap e robots como suporte de descoberta",
        ],
        "a11y": [
            "img sem alt",
            "input sem label",
            "lang na tag html",
            "presenca de title de documento",
        ],
        "content": [
            "palavras por pagina",
            "presenca de heading principal",
        ],
        "performance": [
            "TTFB aproximado",
            "tamanho do HTML",
            "numero de recursos referenciados",
            "recursos potencialmente bloqueantes de renderizacao",
        ],
        "indexacao": [
            "robots.txt e sitemap.xml",
            "paginas noindex",
            "conflitos de canonical",
        ],
        "erros_criticos": [
            "status 4xx/5xx",
            "redirect chains",
            "mixed content",
            "limites de crawl atingidos",
        ],
    }.items():
        sections[key]["measured"] = measured

    appendix = {
        "pages_scanned_html": len(pages),
        "broken_internal_links_count": len(broken_links),
        "http_4xx_5xx_pages_count": len(http_error_pages),
        "noindex_pages_count": len(noindex_pages),
        "missing_meta_description_count": len(meta_missing),
        "missing_title_count": len(title_missing),
        "missing_lang_count": len(missing_lang),
        "images_missing_alt_total": sum(int(page["images_missing_alt"]) for page in pages),
        "inputs_missing_label_total": sum(int(page["inputs_missing_label"]) for page in pages),
        "mixed_content_pages_count": len(mixed_content_pages),
        "redirect_chain_pages_count": len(redirect_chain_pages),
        "robots_present": bool(robots["robots_present"]),
        "sitemap_present": bool(robots["sitemap_present"]),
        "links_checked_internal": int(crawl["links_checked"]),
        "partial_crawl": bool(limit_notes),
    }

    worst_pages: list[dict[str, Any]] = []
    for page in pages:
        seo_issues = 0
        a11y_issues = 0
        content_issues = 0
        perf_issues = 0
        indexacao_issues = 0
        critical_issues = 0

        if not page["title"] or not page["meta_description"] or page["h1_count"] != 1:
            seo_issues += 1
        if page["images_missing_alt"] > 0 or page["inputs_missing_label"] > 0 or not page["lang"]:
            a11y_issues += 1
        if page["word_count"] < 120:
            content_issues += 1
        if page["ttfb_ms"] > 1200 or page["html_size_bytes"] > 512_000 or page["render_blocking_count"] > 5:
            perf_issues += 1
        if "noindex" in str(page["robots_meta"]):
            indexacao_issues += 1
        if page["status"] >= 400 or page["redirect_hops"] >= 3 or page["mixed_content_count"] > 0:
            critical_issues += 1

        total_issues = seo_issues + a11y_issues + content_issues + perf_issues + indexacao_issues + critical_issues
        if total_issues == 0:
            continue
        worst_pages.append(
            {
                "url": page["url"],
                "status": page["status"],
                "total_issues": total_issues,
                "seo_issues": seo_issues,
                "a11y_issues": a11y_issues,
                "content_issues": content_issues,
                "performance_issues": perf_issues,
                "indexacao_issues": indexacao_issues,
                "critical_issues": critical_issues,
            }
        )
    worst_pages.sort(key=lambda item: item["total_issues"], reverse=True)

    return sections, appendix, worst_pages[:20]


def run_detailed_audit(
    url: str,
    *,
    profile: str = "full",
) -> dict[str, Any]:
    normalized = validate_url(url)
    if profile == "summary":
        max_pages = SUMMARY_MAX_PAGES
        max_depth = SUMMARY_MAX_DEPTH
        max_runtime_seconds = SUMMARY_MAX_RUNTIME_SECONDS
        max_link_checks = SUMMARY_MAX_LINK_CHECKS
        per_page_timeout_seconds = SUMMARY_PER_PAGE_TIMEOUT_SECONDS
        include_limit_findings = False
    else:
        max_pages = MAX_PAGES
        max_depth = MAX_DEPTH
        max_runtime_seconds = MAX_RUNTIME_SECONDS
        max_link_checks = MAX_LINK_CHECKS
        per_page_timeout_seconds = PER_PAGE_TIMEOUT_SECONDS
        include_limit_findings = True

    crawl = _crawl_site(
        normalized,
        max_pages=max_pages,
        max_depth=max_depth,
        max_runtime_seconds=max_runtime_seconds,
        max_link_checks=max_link_checks,
        per_page_timeout_seconds=per_page_timeout_seconds,
    )
    sections, appendix, worst_pages = _build_sections(
        crawl,
        include_limit_findings=include_limit_findings,
    )

    return {
        "url": normalized,
        "generated_at": crawl["generated_at"],
        "crawl": {
            "pages_scanned_html": len(crawl["pages"]),
            "runtime_seconds": crawl["runtime_seconds"],
            "max_pages": max_pages,
            "max_depth": max_depth,
            "max_runtime_seconds": max_runtime_seconds,
            "per_page_timeout_seconds": per_page_timeout_seconds,
            "max_link_checks": max_link_checks,
            "skipped_by_robots": crawl["skipped_by_robots"],
            "non_html_urls_found": crawl["non_html_urls"],
            "limit_notes": crawl["limit_notes"],
            "fetch_errors": crawl["fetch_errors"][:20],
        },
        "sections": sections,
        "worst_pages": worst_pages,
        "appendix": appendix,
    }


def _audit_cache_key(url: str, profile: str) -> str:
    return f"{profile}|{url}"


def _get_or_run_detailed_audit(
    url: str,
    *,
    profile: str,
    cache_ttl_seconds: int = AUDIT_CACHE_TTL_SECONDS,
) -> tuple[dict[str, Any], bool]:
    normalized = validate_url(url)
    key = _audit_cache_key(normalized, profile)
    now = time.time()
    cached = _AUDIT_CACHE.get(key)
    if cached and (now - cached[0]) < cache_ttl_seconds:
        return cached[1], True

    detailed = run_detailed_audit(
        normalized,
        profile=profile,
    )
    _AUDIT_CACHE[key] = (now, detailed)
    return detailed, False


def _strip_urls_and_metrics(text: str) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"https?://\S+|www\.\S+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\b\d+(?:[.,]\d+)?%?\b", "", cleaned)
    cleaned = cleaned.replace(".", " ")
    cleaned = re.sub(r"[\r\n\t]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _traduzir_termos_pt(text: str) -> str:
    cleaned = str(text or "")
    trocas = {
        "mixed content": "conteudo misto",
        "render blocking": "bloqueio de renderizacao",
        "title": "titulo",
        "heading": "cabecalho",
    }
    for origem, destino in trocas.items():
        cleaned = re.sub(re.escape(origem), destino, cleaned, flags=re.IGNORECASE)
    return cleaned


def _single_sentence(text: str, fallback: str) -> str:
    cleaned = _traduzir_termos_pt(_strip_urls_and_metrics(text))
    cleaned = re.sub(r"\ban[áa]lise completa\b", "aprofundamento estrategico", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        cleaned = fallback
    parts = re.split(r"(?<=[.!?])\s+", cleaned)
    sentence = ""
    for part in parts:
        candidate = part.strip()
        if candidate:
            sentence = candidate
            break
    if not sentence:
        sentence = cleaned.strip() or fallback
    sentence = re.sub(r"[.!?]+$", "", sentence).strip()
    if not sentence:
        sentence = fallback
    return f"{sentence}."


def _fallback_focus(section_key: str) -> str:
    mapping = {
        "overall": "desempenho digital e potencial de crescimento",
        "seo": "visibilidade organica e geracao de demanda",
        "a11y": "experiencia de navegacao e confianca da marca",
        "content": "clareza da proposta e capacidade de conversao",
        "performance": "fluidez da jornada e tempo de resposta percebido",
        "indexacao": "presenca organica e cobertura de paginas",
        "erros_criticos": "riscos tecnicos com impacto direto em resultados",
    }
    return mapping.get(section_key, "performance digital")


def _rules_based_sentence(section_key: str, section: dict[str, Any]) -> str:
    findings = section.get("findings") or []
    status = str(section.get("status", "attention")).lower()

    focus = _fallback_focus(section_key)
    if findings:
        focus_candidate = _strip_urls_and_metrics(str(findings[0].get("title", ""))).lower()
        if focus_candidate:
            focus = focus_candidate

    if not findings:
        base = (
            f"Nesta leitura inicial, {focus} aparece estavel e o proximo passo e refinar essa frente para ampliar resultados com previsibilidade"
        )
    elif status == "critical":
        base = (
            f"Foram identificados riscos relevantes em {focus} e o proximo passo e priorizar correcoes de maior impacto para proteger conversao e receita"
        )
    elif status == "attention":
        base = (
            f"Ha oportunidades claras em {focus} e o proximo passo e executar melhorias priorizadas para transformar potencial em ganho comercial"
        )
    else:
        base = (
            f"Existem oportunidades pontuais em {focus} e o proximo passo e capturar ganhos adicionais com ajustes de alto retorno"
        )

    fallback = "O proximo passo e aplicar melhorias objetivas nesta frente para elevar resultado comercial"
    return _single_sentence(base, fallback)


def _llm_executive_summary(sections: dict[str, dict[str, Any]]) -> dict[str, str]:
    api_key = (os.getenv("LLM_API_KEY") or "").strip()
    if not api_key:
        raise LLMUnavailableError("LLM_API_KEY is missing")

    is_groq_key = api_key.startswith("gsk_")
    default_model = "llama-3.1-8b-instant" if is_groq_key else "gpt-4o-mini"
    model = (os.getenv("LLM_MODEL") or default_model).strip() or default_model

    base_url = "https://api.groq.com/openai/v1" if is_groq_key else "https://api.openai.com/v1"
    completions_url = f"{base_url}/chat/completions"
    payload = {}
    for key in SECTION_KEYS:
        section = sections.get(key, {})
        payload[key] = {
            "status": section.get("status"),
            "summary": section.get("summary"),
            "findings": [
                {
                    "severity": item.get("severity"),
                    "title": item.get("title"),
                    "how_to_fix": item.get("how_to_fix"),
                }
                for item in (section.get("findings") or [])[:3]
            ],
            "next_actions": (section.get("next_actions") or [])[:3],
        }

    prompt = (
        "Write one executive sentence per section in Brazilian Portuguese. "
        "Return JSON with exactly these keys: overall, seo, a11y, content, performance, indexacao, erros_criticos. "
        "Rules: one sentence only per key; no URLs; no numeric metrics; no bullet/list formatting; "
        "be actionable and grounded only on provided findings; use a consultative commercial tone that highlights "
        "risk or opportunity; do not mention the phrase analise completa."
    )

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                completions_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                },
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise LLMUnavailableError(f"LLM request returned status {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        raise LLMUnavailableError("LLM request failed") from exc

    try:
        raw = response.json()["choices"][0]["message"]["content"]
        parsed = json.loads(raw)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise LLMUnavailableError("LLM response parsing failed") from exc

    if not isinstance(parsed, dict):
        raise LLMUnavailableError("LLM response format is invalid")

    summary: dict[str, str] = {}
    for key in SECTION_KEYS:
        value = parsed.get(key)
        if not isinstance(value, str):
            raise LLMUnavailableError(f"LLM response is missing key: {key}")
        fallback = "O proximo passo e aplicar melhorias objetivas nesta frente para elevar resultado comercial"
        summary[key] = _single_sentence(value, fallback)
    return summary


def run_executive_summary(url: str) -> dict[str, str]:
    normalized = validate_url(url)
    now = time.time()
    cached = _SUMMARY_CACHE.get(normalized)
    if cached and (now - cached[0]) < SUMMARY_CACHE_TTL_SECONDS:
        return dict(cached[1])

    full_key = _audit_cache_key(normalized, "full")
    cached_full = _AUDIT_CACHE.get(full_key)
    if cached_full and (now - cached_full[0]) < AUDIT_CACHE_TTL_SECONDS:
        detailed = cached_full[1]
    else:
        detailed, _ = _get_or_run_detailed_audit(
            normalized,
            profile="summary",
            cache_ttl_seconds=SUMMARY_CACHE_TTL_SECONDS,
        )
    sections = detailed["sections"]

    llm_summary = _llm_executive_summary(sections)
    _SUMMARY_CACHE[normalized] = (now, llm_summary)
    return llm_summary


def _status_pt(status: str) -> str:
    mapping = {
        "ok": "ok",
        "attention": "atencao",
        "critical": "critico",
    }
    return mapping.get(str(status).lower(), "atencao")


def _categoria_pt(chave: str) -> str:
    nomes = {
        "overall": "visao_geral",
        "seo": "seo",
        "a11y": "acessibilidade",
        "content": "conteudo",
        "performance": "performance",
        "indexacao": "indexacao",
        "erros_criticos": "erros_criticos",
    }
    return nomes.get(chave, chave)


def _finding_pt(finding: dict[str, Any]) -> dict[str, Any]:
    evidencias = []
    for item in finding.get("evidence") or []:
        evidencias.append(
            {
                "url": item.get("url"),
                "seletor": item.get("selector"),
                "valor": item.get("value"),
                "metrica": item.get("metric"),
            }
        )

    severidade_map = {
        "critical": "critica",
        "high": "alta",
        "medium": "media",
        "low": "baixa",
    }

    return {
        "id": finding.get("id"),
        "severidade": severidade_map.get(str(finding.get("severity")).lower(), "media"),
        "titulo": finding.get("title"),
        "descricao": finding.get("description"),
        "impacto": finding.get("impact"),
        "como_corrigir": finding.get("how_to_fix"),
        "evidencias": evidencias,
        "urls_afetadas": finding.get("affected_urls") or [],
    }


def run_report_json(url: str) -> dict[str, Any]:
    detailed, veio_do_cache = _get_or_run_detailed_audit(
        url,
        profile="full",
        cache_ttl_seconds=AUDIT_CACHE_TTL_SECONDS,
    )

    secoes_raw = detailed["sections"]
    overall = secoes_raw["overall"]

    pontuacoes = {}
    for key in ["seo", "a11y", "content", "performance", "indexacao", "erros_criticos"]:
        sec = secoes_raw[key]
        pontuacoes[_categoria_pt(key)] = {
            "score": int(sec.get("score", 0)),
            "status": _status_pt(str(sec.get("status", "attention"))),
        }

    secoes = []
    for key in ["seo", "a11y", "content", "performance", "indexacao", "erros_criticos"]:
        sec = secoes_raw[key]
        secoes.append(
            {
                "categoria": _categoria_pt(key),
                "score": int(sec.get("score", 0)),
                "status": _status_pt(str(sec.get("status", "attention"))),
                "resumo": sec.get("summary", ""),
                "o_que_foi_medido": sec.get("measured") or [],
                "principais_achados": [_finding_pt(item) for item in (sec.get("findings") or [])[:10]],
                "proximas_acoes": (sec.get("next_actions") or [])[:5],
            }
        )

    piores_paginas = []
    for item in detailed.get("worst_pages") or []:
        piores_paginas.append(
            {
                "url": item.get("url"),
                "status_http": item.get("status"),
                "total_achados": item.get("total_issues"),
                "achados_seo": item.get("seo_issues"),
                "achados_acessibilidade": item.get("a11y_issues"),
                "achados_conteudo": item.get("content_issues"),
                "achados_performance": item.get("performance_issues"),
                "achados_indexacao": item.get("indexacao_issues"),
                "achados_criticos": item.get("critical_issues"),
            }
        )

    appendix = detailed.get("appendix") or {}
    apendice = {
        "paginas_html_analisadas": appendix.get("pages_scanned_html"),
        "links_internos_quebrados": appendix.get("broken_internal_links_count"),
        "paginas_com_erro_http": appendix.get("http_4xx_5xx_pages_count"),
        "paginas_noindex": appendix.get("noindex_pages_count"),
        "paginas_sem_meta_description": appendix.get("missing_meta_description_count"),
        "paginas_sem_title": appendix.get("missing_title_count"),
        "paginas_sem_lang": appendix.get("missing_lang_count"),
        "imagens_sem_alt": appendix.get("images_missing_alt_total"),
        "inputs_sem_label": appendix.get("inputs_missing_label_total"),
        "paginas_com_mixed_content": appendix.get("mixed_content_pages_count"),
        "paginas_com_redirect_chain": appendix.get("redirect_chain_pages_count"),
        "robots_encontrado": appendix.get("robots_present"),
        "sitemap_encontrado": appendix.get("sitemap_present"),
        "links_internos_verificados": appendix.get("links_checked_internal"),
        "crawl_parcial": appendix.get("partial_crawl"),
    }

    return {
        "url": detailed.get("url"),
        "gerado_em": detailed.get("generated_at"),
        "origem_dados": "cache" if veio_do_cache else "processamento_novo",
        "resumo_executivo": {
            "score_geral": int(overall.get("score", 0)),
            "status_geral": _status_pt(str(overall.get("status", "attention"))),
            "mensagem_geral": overall.get("summary", ""),
            "pontuacoes": pontuacoes,
        },
        "secoes": secoes,
        "piores_paginas": piores_paginas,
        "apendice": apendice,
    }
