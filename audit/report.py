from __future__ import annotations

from typing import Any

from .analyzer import run_detailed_audit
from .constants import SECTION_KEYS
from .llm import LLMUnavailableError, llm_executive_summary


def _status_pt(status: str) -> str:
    mapping = {
        "ok": "Ótimo",
        "attention": "Atenção",
        "critical": "Crítico",
    }
    return mapping.get(str(status).lower(), "Atenção")


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
        evidencias.append({
            "url": item.get("url"),
            "seletor": item.get("selector"),
            "valor": item.get("value"),
            "metrica": item.get("metric"),
        })

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


def run_executive_summary(url: str) -> dict[str, Any]:
    detailed = run_detailed_audit(url)
    sections = detailed["sections"]

    summary = llm_executive_summary(sections)
    appendix = detailed.get("appendix") or {}

    result: dict[str, Any] = {}
    for key in SECTION_KEYS:
        sec = sections.get(key, {})
        entry: dict[str, Any] = {
            "score": int(sec.get("score", 0)),
            "status": _status_pt(str(sec.get("status", "attention"))),
            "resumo": summary.get(key, ""),
        }
        if key == "erros_criticos":
            entry["total"] = len(sec.get("findings") or [])
        result[_categoria_pt(key)] = entry

    result["indexacao"] = {"indexado": bool(appendix.get("site_indexado", False))}
    return result


def run_report_json(url: str) -> dict[str, Any]:
    detailed = run_detailed_audit(url)

    secoes_raw = detailed["sections"]
    overall = secoes_raw["overall"]

    pontuacoes = {}
    for key in ["seo", "a11y", "content", "performance", "erros_criticos"]:
        sec = secoes_raw[key]
        pontuacoes[_categoria_pt(key)] = {
            "score": int(sec.get("score", 0)),
            "status": _status_pt(str(sec.get("status", "attention"))),
        }

    secoes = []
    for key in ["seo", "a11y", "content", "performance", "indexacao", "erros_criticos"]:
        sec = secoes_raw[key]
        if key == "indexacao":
            secoes.append({
                "categoria": "indexacao",
                "indexado": bool((detailed.get("appendix") or {}).get("site_indexado", False)),
            })
            continue
        secoes.append({
            "categoria": _categoria_pt(key),
            "score": int(sec.get("score", 0)),
            "status": _status_pt(str(sec.get("status", "attention"))),
            "resumo": sec.get("summary", ""),
            "o_que_foi_medido": sec.get("measured") or [],
            "principais_achados": [_finding_pt(item) for item in (sec.get("findings") or [])[:10]],
            "proximas_acoes": (sec.get("next_actions") or [])[:5],
        })

    piores_paginas = []
    for item in detailed.get("worst_pages") or []:
        piores_paginas.append({
            "url": item.get("url"),
            "status_http": item.get("status"),
            "total_achados": item.get("total_issues"),
            "achados_seo": item.get("seo_issues"),
            "achados_acessibilidade": item.get("a11y_issues"),
            "achados_conteudo": item.get("content_issues"),
            "achados_performance": item.get("performance_issues"),
            "achados_indexacao": item.get("indexacao_issues"),
            "achados_criticos": item.get("critical_issues"),
        })

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
        "indexado": appendix.get("indexado"),
    }

    return {
        "url": detailed.get("url"),
        "gerado_em": detailed.get("generated_at"),
        "origem_dados": "processamento_novo",
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
