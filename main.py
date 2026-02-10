from __future__ import annotations

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from audit import run_executive_summary, run_report_json, validate_url


class AuditRequest(BaseModel):
    url: str


app = FastAPI(
    title="Simple Site Audit API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.post("/report")
def report(request: AuditRequest) -> dict:
    try:
        normalized_url = validate_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run_report_json(normalized_url)


@app.post("/analyze_summary")
def analyze_summary(request: AuditRequest) -> dict[str, str]:
    try:
        normalized_url = validate_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run_executive_summary(normalized_url)
