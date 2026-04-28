from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from .constants import SECTION_KEYS


class LLMUnavailableError(RuntimeError):
    pass


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
        "mixed content": "conteúdo misto",
        "render blocking": "bloqueio de renderização",
        "title": "título",
        "heading": "cabeçalho",
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
        "seo": "visibilidade orgânica e geração de demanda",
        "a11y": "experiência de navegação e confiança da marca",
        "content": "clareza da proposta e capacidade de conversão",
        "performance": "fluidez da jornada e tempo de resposta percebido",
        "erros_criticos": "riscos técnicos com impacto direto em resultados",
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
        base = f"Nesta leitura inicial, {focus} aparece estável e o próximo passo é refinar essa frente para ampliar resultados com previsibilidade"
    elif status == "critical":
        base = f"Foram identificados riscos relevantes em {focus} e o próximo passo é priorizar correções de maior impacto para proteger conversão e receita"
    elif status == "attention":
        base = f"Há oportunidades claras em {focus} e o próximo passo é executar melhorias priorizadas para transformar potencial em ganho comercial"
    else:
        base = f"Existem oportunidades pontuais em {focus} e o próximo passo é capturar ganhos adicionais com ajustes de alto retorno"

    fallback = "O próximo passo é aplicar melhorias objetivas nesta frente para elevar resultado comercial"
    return _single_sentence(base, fallback)


def llm_executive_summary(sections: dict[str, dict[str, Any]]) -> dict[str, str]:
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
        "Return JSON with exactly these keys: overall, seo, a11y, content, performance, erros_criticos. "
        "Rules: one sentence only per key; no URLs; no numeric metrics; no bullet/list formatting; "
        "be actionable and grounded only on provided findings; use a consultative commercial tone that highlights "
        "risk or opportunity; do not mention the phrase analise completa."
    )

    request_body = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }

    parsed: dict | None = None
    for _ in range(3):
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    completions_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=request_body,
                )
                response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            candidate = json.loads(raw)
            if isinstance(candidate, dict) and all(
                isinstance(candidate.get(k), str) for k in SECTION_KEYS
            ):
                parsed = candidate
                break
        except httpx.HTTPStatusError as exc:
            raise LLMUnavailableError(f"LLM request returned status {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailableError("LLM request failed") from exc
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            pass

    summary: dict[str, str] = {}
    for key in SECTION_KEYS:
        fallback = _rules_based_sentence(key, sections.get(key, {}))
        value = (parsed or {}).get(key)
        if not isinstance(value, str) or not value.strip():
            summary[key] = fallback
        else:
            summary[key] = _single_sentence(value, fallback)
    return summary
