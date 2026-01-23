from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from app.engine.analyzer import analyze
from app.engine.report import build_pdf_report

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


async def run_cli(
    url: str,
    mode: str = "site",
    max_pages: int = 500,
    max_depth: int = 5,
    out_json: str = "outputs/alf-scan-result.json",
):
    result = await analyze(url=url, mode=mode, max_pages=max_pages, max_depth=max_depth)

    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    pdf_path = Path(out_json).with_suffix(".pdf")
    build_pdf_report(result, str(pdf_path))

    print(result.get("report", ""))


if __name__ == "__main__":
    asyncio.run(
        run_cli(
            "https://uniaoconstrucoes.com.br/",
            mode="site",
            max_pages=500,
            max_depth=5,
        )
    )
