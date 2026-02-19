from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from audit import LLMUnavailableError, run_executive_summary, run_report_json, validate_url


class AuditRequest(BaseModel):
    url: str


API_TOKEN = os.getenv("API_TOKEN", "").strip()


def _validate_api_token(x_api_token: str | None) -> None:
    if not API_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="server misconfigured: API_TOKEN is missing",
        )
    if x_api_token != API_TOKEN:
        raise HTTPException(status_code=401, detail="invalid api token")


app = FastAPI(
    title="Simple Site Audit API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.post("/report")
def report(
    request: AuditRequest,
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> dict:
    _validate_api_token(x_api_token)
    try:
        normalized_url = validate_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run_report_json(normalized_url)


@app.post("/analyze_summary")
def analyze_summary(
    request: AuditRequest,
    x_api_token: str | None = Header(default=None, alias="X-API-Token"),
) -> dict[str, str]:
    _validate_api_token(x_api_token)
    try:
        normalized_url = validate_url(request.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return run_executive_summary(normalized_url)
    except LLMUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
