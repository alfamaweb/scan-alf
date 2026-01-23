from __future__ import annotations

from collections import deque
from difflib import SequenceMatcher
from typing import Literal, Optional
from urllib.parse import urlparse

from app.engine.checks import run_basic_checks
from app.engine.crawler import normalize, same_domain
from app.engine.extractor import extract_basic
from app.engine.fetcher import PlaywrightFetcher
from app.engine.scoring import compute_scores
from app.engine.report_generator import generate_report


AnalyzeMode = Literal["single_page", "site"]


async def _safe_fetch(fetcher: PlaywrightFetcher, url: str) -> tuple[int, str, Optional[str]]:
    try:
        status, html = await fetcher.fetch_html(url)
        return status, html, None
    except Exception as exc:
        return 0, "", f"{type(exc).__name__}: {exc}"


def _normalize_root(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme:
        return f"https://{url}"
    return url


def _path_key(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path if path else "/"


def _page_signature(page: dict) -> str:
    title = page.get("title") or ""
    snippet = page.get("text_snippet") or ""
    return " ".join(f"{title} {snippet}".lower().split())


def _find_page_by_path(pages: list[dict], path: str) -> Optional[dict]:
    target = path if path.startswith("/") else f"/{path}"
    for page in pages:
        if _path_key(page.get("url", "")) == target:
            return page
    return None


async def _detect_duplicate_home(fetcher: PlaywrightFetcher, root_url: str, pages: list[dict]) -> dict:
    root_page = _find_page_by_path(pages, "/")
    home_page = _find_page_by_path(pages, "/home")
    home_checked = False
    home_status = None

    if not home_page:
        home_url = root_url.rstrip("/") + "/home"
        status, html, _ = await _safe_fetch(fetcher, home_url)
        home_checked = True
        home_status = status
        if status >= 200 and html:
            home_page = extract_basic(home_url, status, html)

    if not root_page or not home_page:
        return {
            "home_checked": home_checked,
            "home_status": home_status,
            "home_similarity": None,
            "duplicate_home": False,
        }

    sig_root = _page_signature(root_page)
    sig_home = _page_signature(home_page)
    similarity = SequenceMatcher(None, sig_root, sig_home).ratio() if sig_root and sig_home else 0.0
    duplicate = similarity >= 0.9 and (
        (root_page.get("title") and root_page.get("title") == home_page.get("title"))
        or similarity >= 0.95
    )

    return {
        "home_checked": home_checked,
        "home_status": home_status,
        "home_similarity": round(similarity, 3),
        "duplicate_home": duplicate,
    }


async def analyze(
    url: str,
    mode: AnalyzeMode = "site",
    max_pages: int = 500,
    max_depth: int = 5,
    context: Optional[dict] = None,
) -> dict:
    root_url = _normalize_root(url)
    mode = "site"
    max_pages = max(1, int(max_pages))
    max_depth = max(0, int(max_depth))
    fetcher = PlaywrightFetcher()

    pages: list[dict] = []
    findings: list[dict] = []

    if mode == "site":
        root = normalize(root_url)
        seen = {root}
        queue = deque([(root, 0)])

        while queue and len(pages) < max_pages:
            current, depth = queue.popleft()
            status, html, error = await _safe_fetch(fetcher, current)
            page = extract_basic(current, status, html)
            if error:
                page["error"] = error
            pages.append(page)
            findings.extend(run_basic_checks(page))

            if depth >= max_depth:
                continue

            for link in page.get("internal_links", []):
                nxt = normalize(link)
                if not nxt.startswith(("http://", "https://")):
                    continue
                if not same_domain(root, nxt):
                    continue
                if nxt in seen:
                    continue
                seen.add(nxt)
                queue.append((nxt, depth + 1))
    else:
        status, html, error = await _safe_fetch(fetcher, root_url)
        page = extract_basic(root_url, status, html)
        if error:
            page["error"] = error
        pages.append(page)
        findings.extend(run_basic_checks(page))

    scores = compute_scores(findings)

    diagnostics = await _detect_duplicate_home(fetcher, root_url, pages)

    result = {
        "input": {"url": root_url, "mode": mode, "max_pages": max_pages, "max_depth": max_depth},
        "meta": {"pages_scanned": len(pages)},
        "pages": pages,
        "findings": findings,
        "scores": scores,
        "diagnostics": diagnostics,
        "context": context or {},
    }
    if mode == "single_page" and pages:
        result["page"] = pages[0]

    result["report"] = generate_report(result, context=context)
    result["summary"] = result["report"]

    return result
