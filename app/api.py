from __future__ import annotations

import asyncio
import re
import sys
import unicodedata
import uuid
from pathlib import Path
from typing import Annotated, Literal, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, validator

from app.engine.analyzer import analyze
from app.engine.report import build_pdf_report

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


ROOT_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = ROOT_DIR / "frontend"
OUTPUT_DIR = ROOT_DIR / "outputs"

app = FastAPI(title="ALF Scan API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


class AnalyzeRequest(BaseModel):
    url: str
    mode: Literal["single_page", "site"] = "site"
    max_pages: Annotated[int, Field(ge=1, le=1000)] = 500
    max_depth: Annotated[int, Field(ge=0, le=8)] = 5
    brand_name: Optional[str] = None
    segment: Optional[str] = None
    city: Optional[str] = None
    product: Optional[str] = None
    consultancy: Optional[str] = None
    differentiators: list[str] = Field(default_factory=list)
    social: list[str] = Field(default_factory=list)

    @validator("url")
    def normalize_url(cls, value: str) -> str:
        clean = value.strip()
        if not clean:
            raise ValueError("URL vazia.")
        if not clean.startswith(("http://", "https://")):
            clean = f"https://{clean}"
        return clean


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/")
def index():
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend nao encontrado.")
    return FileResponse(str(index_path))

def _slugify(value: str, max_len: int = 60) -> str:
    if not value:
        return "site"
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    if not cleaned:
        return "site"
    return cleaned[:max_len].strip("-") or "site"

@app.post("/analyze")
async def analyze_endpoint(req: AnalyzeRequest) -> dict:
    context = {
        "brand_name": req.brand_name,
        "segment": req.segment,
        "city": req.city,
        "product": req.product,
        "consultancy": req.consultancy or "AlfamaWeb",
        "differentiators": req.differentiators or None,
        "social": req.social or None,
    }
    context = {key: value for key, value in context.items() if value}

    result = await analyze(
        url=str(req.url),
        mode="site",
        max_pages=req.max_pages,
        max_depth=req.max_depth,
        context=context,
    )

    job_id = str(uuid.uuid4())
    result["job_id"] = job_id

    pages = result.get("pages") or []
    title = None
    if pages:
        title = pages[0].get("title")
    if not title:
        title = result.get("input", {}).get("url", "")
    slug = _slugify(title)
    report_filename = f"analise-{slug}-{job_id[:8]}.pdf"
    report_path = OUTPUT_DIR / report_filename
    build_pdf_report(result, str(report_path))
    result["report_path"] = f"/report/{report_filename}"
    result["report_filename"] = report_filename

    return result


@app.get("/report/{filename}")
def report_endpoint(filename: str):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo invalido.")
    report_path = OUTPUT_DIR / filename
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Relatorio nao encontrado.")
    return FileResponse(
        path=str(report_path),
        media_type="application/pdf",
        filename=report_path.name,
    )
