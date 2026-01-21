from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich import print

from app.fetcher import PlaywrightFetcher
from app.extractor import extract_basic
from app.checks import run_basic_checks
from app.scoring import compute_scores
from app.llm_groq import generate_summary


async def analyze_one(url: str, out_path: str = "outputs/mvp3_result.json") -> None:
    fetcher = PlaywrightFetcher()
    status, html = await fetcher.fetch_html(url)
    page = extract_basic(url, status, html)

    findings = run_basic_checks(page)
    scores = compute_scores(findings)

    result = {
        "page": page,
        "findings": findings,
        "scores": scores,
    }

    # LLM summary (Groq)
    summary = generate_summary(result)
    result["summary"] = summary

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("[green]ALF Scan MVP3 OK[/green]")
    print(f"Saved: {out_path}")
    print(f"Findings: {len(findings)}")
    print(f"Overall score: {scores['overall']}")
    print("\n[bold]Summary:[/bold]\n" + summary)


if __name__ == "__main__":
    asyncio.run(analyze_one("https://uniaoconstrucoes.com.br/"))
