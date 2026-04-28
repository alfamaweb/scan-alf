from __future__ import annotations

from typing import Any

from .constants import (
    MAX_DEPTH,
    MAX_LINK_CHECKS,
    MAX_PAGES,
    MAX_RUNTIME_SECONDS,
    PER_PAGE_TIMEOUT_SECONDS,
    SEVERITY_ORDER,
    SEVERITY_PENALTY,
)
from .crawler import crawl_site, validate_url


def _make_evidence(
    url: str,
    selector: str | None = None,
    value: Any | None = None,
    metric: Any | None = None,
) -> dict[str, Any]:
    return {"url": url, "selector": selector, "value": value, "metric": metric}


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
        next_actions = ["Manter monitoramento recorrente e validar regressão semanal."]

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
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    pages = crawl["pages"]
    broken_links = crawl["broken_internal_links"]
    robots = crawl["robots"]
    limit_notes = crawl["limit_notes"]
    ssl_error_detected = crawl.get("ssl_error_detected", False)
    crawl_blocked = bool(robots.get("crawl_blocked", False))

    def _has_noindex(page: dict[str, Any]) -> bool:
        return "noindex" in str(page.get("robots_meta") or "").lower()

    homepage_noindex = bool(pages and _has_noindex(pages[0]))
    all_pages_noindex = bool(pages and all(_has_noindex(p) for p in pages))
    no_pages_crawled = not pages

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
        seo_findings.append(_make_finding(
            "seo_title_missing", "high", "Páginas sem title",
            f"{len(title_missing)} páginas HTML sem tag <title>.",
            "Prejudica relevância orgânica e CTR.",
            "Definir um title único e descritivo por página.",
            [_make_evidence(title_missing[0]["url"], selector="title", value="", metric=len(title_missing))],
            _top_urls(title_missing),
        ))

    if title_len_bad:
        seo_findings.append(_make_finding(
            "seo_title_length", "medium", "Titles fora do tamanho recomendado",
            f"{len(title_len_bad)} páginas com title curto ou longo demais.",
            "Pode reduzir clareza do snippet no buscador.",
            "Manter titles entre 15 e 60 caracteres.",
            [_make_evidence(title_len_bad[0]["url"], selector="title", metric=len(title_len_bad))],
            _top_urls(title_len_bad),
        ))

    if meta_missing:
        seo_findings.append(_make_finding(
            "seo_meta_description_missing", "medium", "Meta description ausente",
            f"{len(meta_missing)} páginas sem meta description.",
            "Diminui controle sobre texto exibido no resultado de busca.",
            "Adicionar meta description única e objetiva em cada página.",
            [_make_evidence(meta_missing[0]["url"], selector='meta[name="description"]', value="", metric=len(meta_missing))],
            _top_urls(meta_missing),
        ))

    if meta_len_bad:
        seo_findings.append(_make_finding(
            "seo_meta_description_length", "low", "Meta descriptions fora do tamanho recomendado",
            f"{len(meta_len_bad)} páginas com meta description curta ou longa demais.",
            "Pode afetar compreensão do snippet.",
            "Ajustar meta descriptions para faixa entre 70 e 160 caracteres.",
            [_make_evidence(meta_len_bad[0]["url"], selector='meta[name="description"]')],
            _top_urls(meta_len_bad),
        ))

    if canonical_missing:
        seo_findings.append(_make_finding(
            "seo_canonical_missing", "medium", "Canonical ausente",
            f"{len(canonical_missing)} páginas sem link canonical.",
            "Pode dificultar consolidação de sinais para URLs similares.",
            "Adicionar <link rel='canonical'> em páginas indexáveis.",
            [_make_evidence(canonical_missing[0]["url"], selector="link[rel=canonical]")],
            _top_urls(canonical_missing),
        ))

    if h1_bad:
        seo_findings.append(_make_finding(
            "seo_h1_count", "medium", "Estrutura de H1 inconsistente",
            f"{len(h1_bad)} páginas com quantidade de H1 diferente de 1.",
            "Pode reduzir clareza semântica da página.",
            "Garantir exatamente um H1 principal por página.",
            [_make_evidence(h1_bad[0]["url"], selector="h1", metric=len(h1_bad))],
            _top_urls(h1_bad),
        ))

    if broken_links:
        severity = "critical" if len(broken_links) >= 10 else "high"
        seo_findings.append(_make_finding(
            "seo_broken_internal_links", severity, "Links internos quebrados",
            f"{len(broken_links)} links internos retornando erro (4xx/5xx/timeout).",
            "Impacta rastreabilidade, UX e distribuição de autoridade interna.",
            "Corrigir URLs quebradas e atualizar links de navegacao.",
            [_make_evidence(broken_links[0]["url"], metric=broken_links[0]["status"])],
            [item["url"] for item in broken_links[:25]],
        ))

    if missing_alt_pages:
        total_missing_alt = sum(int(page["images_missing_alt"]) for page in missing_alt_pages)
        severity = "high" if total_missing_alt >= 20 else "medium"
        a11y_findings.append(_make_finding(
            "a11y_img_alt_missing", severity, "Imagens sem texto alternativo",
            f"{total_missing_alt} imagens sem alt em {len(missing_alt_pages)} páginas.",
            "Prejudica acessibilidade para leitores de tela.",
            "Definir atributo alt descritivo em todas as imagens relevantes.",
            [_make_evidence(missing_alt_pages[0]["url"], selector="img[alt]", metric=total_missing_alt)],
            _top_urls(missing_alt_pages),
        ))

    if missing_label_pages:
        total_missing_label = sum(int(page["inputs_missing_label"]) for page in missing_label_pages)
        a11y_findings.append(_make_finding(
            "a11y_input_label_missing", "high", "Campos de formulário sem label",
            f"{total_missing_label} inputs sem label associada.",
            "Dificulta navegação com tecnologia assistiva.",
            "Associar labels via for/id ou usar aria-label/aria-labelledby.",
            [_make_evidence(missing_label_pages[0]["url"], selector="input", metric=total_missing_label)],
            _top_urls(missing_label_pages),
        ))

    if missing_lang:
        a11y_findings.append(_make_finding(
            "a11y_lang_missing", "medium", "Atributo lang ausente",
            f"{len(missing_lang)} páginas sem atributo lang na tag html.",
            "Pode reduzir compatibilidade com leitores de tela.",
            "Definir lang apropriado no elemento <html>.",
            [_make_evidence(missing_lang[0]["url"], selector="html[lang]")],
            _top_urls(missing_lang),
        ))

    if title_missing:
        a11y_findings.append(_make_finding(
            "a11y_title_missing", "medium", "Título da página ausente",
            f"{len(title_missing)} páginas sem título de documento.",
            "Compromete contexto de navegação para usuários assistivos.",
            "Adicionar tag <title> descritiva em todas as páginas.",
            [_make_evidence(title_missing[0]["url"], selector="title")],
            _top_urls(title_missing),
        ))

    if thin_content:
        content_findings.append(_make_finding(
            "content_thin_pages", "medium", "Conteudo muito curto",
            f"{len(thin_content)} páginas com menos de 120 palavras.",
            "Pode reduzir capacidade de ranqueamento e conversão.",
            "Expandir conteudo util com contexto, prova e CTA claros.",
            [_make_evidence(thin_content[0]["url"], metric=thin_content[0]["word_count"])],
            _top_urls(thin_content),
        ))

    if low_heading_structure:
        content_findings.append(_make_finding(
            "content_missing_h1", "medium", "Estrutura sem heading principal",
            f"{len(low_heading_structure)} páginas sem H1.",
            "Reduz clareza da proposta principal para usuários e buscadores.",
            "Incluir heading principal alinhado com o objetivo da página.",
            [_make_evidence(low_heading_structure[0]["url"], selector="h1")],
            _top_urls(low_heading_structure),
        ))

    if slow_pages:
        performance_findings.append(_make_finding(
            "perf_slow_ttfb", "high", "TTFB elevado",
            f"{len(slow_pages)} páginas com TTFB acima de 1200ms.",
            "Aumenta tempo de carregamento percebido.",
            "Revisar backend, cache e latência de servidor.",
            [_make_evidence(slow_pages[0]["url"], metric=slow_pages[0]["ttfb_ms"])],
            _top_urls(slow_pages),
        ))

    if heavy_html:
        performance_findings.append(_make_finding(
            "perf_heavy_html", "medium", "HTML muito pesado",
            f"{len(heavy_html)} páginas com HTML acima de 500KB.",
            "Pode aumentar tempo de download e parse.",
            "Reduzir markup redundante e componentes inline excessivos.",
            [_make_evidence(heavy_html[0]["url"], metric=heavy_html[0]["html_size_bytes"])],
            _top_urls(heavy_html),
        ))

    if high_request_pages:
        performance_findings.append(_make_finding(
            "perf_many_requests", "medium", "Muitos recursos na página",
            f"{len(high_request_pages)} páginas com mais de 80 recursos referenciados.",
            "Aumenta custo de renderização e transferências.",
            "Consolidar e otimizar scripts, CSS e imagens.",
            [_make_evidence(high_request_pages[0]["url"], metric=high_request_pages[0]["resource_count"])],
            _top_urls(high_request_pages),
        ))

    if render_blocking:
        performance_findings.append(_make_finding(
            "perf_render_blocking", "medium", "Recursos bloqueando renderização",
            f"{len(render_blocking)} páginas com mais de 5 recursos bloqueantes no head.",
            "Pode atrasar exibição de conteúdo acima da dobra.",
            "Aplicar defer/async em scripts e otimizar CSS crítico.",
            [_make_evidence(render_blocking[0]["url"], metric=render_blocking[0]["render_blocking_count"])],
            _top_urls(render_blocking),
        ))

    site_indexado = not crawl_blocked and not homepage_noindex and not all_pages_noindex and not no_pages_crawled

    if not site_indexado:
        motivo = []
        if crawl_blocked:
            motivo.append("robots.txt bloqueando rastreamento (Disallow: /)")
        if homepage_noindex:
            motivo.append("homepage com meta robots noindex")
        if all_pages_noindex and not homepage_noindex:
            motivo.append("todas as páginas rastreadas com meta robots noindex")
        if no_pages_crawled and not crawl_blocked:
            motivo.append("nenhuma página HTML acessível durante o rastreamento")
        indexacao_findings.append(_make_finding(
            "indexacao_nao_indexado", "critical", "Site não indexado",
            f"O site não está sendo indexado: {', '.join(motivo)}.",
            "O site não aparece nos resultados de busca orgânica.",
            "Corrigir as restrições de indexação identificadas.",
            [_make_evidence(crawl["url"])],
            [crawl["url"]],
        ))

    if http_error_pages:
        sev = "critical" if any(int(page["status"]) >= 500 for page in http_error_pages) else "high"
        critical_findings.append(_make_finding(
            "critical_http_errors", sev, "Páginas com erro HTTP",
            f"{len(http_error_pages)} páginas HTML com status 4xx/5xx ou timeout.",
            "Interrompe jornada do usuário e rastreio.",
            "Corrigir rotas quebradas e falhas de servidor prioritariamente.",
            [_make_evidence(http_error_pages[0]["url"], metric=http_error_pages[0]["status"])],
            _top_urls(http_error_pages),
        ))

    if redirect_chain_pages:
        critical_findings.append(_make_finding(
            "critical_redirect_chains", "high", "Cadeias de redirecionamento longas",
            f"{len(redirect_chain_pages)} páginas com cadeia de 3+ redirecionamentos.",
            "Aumenta latência e pode causar perda de sinal SEO.",
            "Reduzir para no máximo um redirecionamento por URL.",
            [_make_evidence(redirect_chain_pages[0]["url"], metric=redirect_chain_pages[0]["redirect_hops"])],
            _top_urls(redirect_chain_pages),
        ))

    if mixed_content_pages:
        critical_findings.append(_make_finding(
            "critical_mixed_content", "high", "Mixed content em páginas HTTPS",
            f"{len(mixed_content_pages)} páginas carregando recursos HTTP em contexto HTTPS.",
            "Pode causar bloqueio de recursos e alertas de segurança.",
            "Migrar todos os recursos para HTTPS.",
            [_make_evidence(mixed_content_pages[0]["url"], metric=mixed_content_pages[0]["mixed_content_count"])],
            _top_urls(mixed_content_pages),
        ))

    if ssl_error_detected:
        critical_findings.append(_make_finding(
            "critical_ssl_error", "critical", "Certificado SSL inválido ou não verificável",
            "O certificado HTTPS do site não passou na verificação de autenticidade.",
            "Navegadores podem exibir aviso de segurança, prejudicando confiança e conversão.",
            "Renovar ou substituir o certificado SSL por um emitido por autoridade reconhecida.",
            [_make_evidence(crawl["url"])],
            [crawl["url"]],
        ))

    if limit_notes:
        note_text = "; ".join(limit_notes)
        critical_findings.append(_make_finding(
            "critical_partial_crawl", "critical", "Crawl parcial por limite de segurança",
            f"A varredura foi interrompida antes de cobrir todo o site: {note_text}",
            "Resultados representam amostra parcial do site.",
            "Reexecutar auditoria apos reduzir complexidade de rastreamento ou revisar arquitetura.",
            [_make_evidence(crawl["url"], metric=note_text)],
            [crawl["url"]],
        ))

    seo_summary = (
        f"{len(seo_findings)} achados SEO em {len(pages)} páginas HTML analisadas."
        if pages else "Nenhuma página HTML analisada para SEO."
    )
    a11y_summary = (
        f"{len(a11y_findings)} achados de acessibilidade em verificações básicas."
        if pages else "Nenhuma página HTML analisada para acessibilidade."
    )
    content_summary = (
        f"{len(content_findings)} achados de conteúdo com foco em cobertura e estrutura."
        if pages else "Nenhuma página HTML analisada para conteúdo."
    )
    performance_summary = (
        f"{len(performance_findings)} achados de performance por proxies leves (TTFB, tamanho HTML e recursos)."
        if pages else "Nenhuma página HTML analisada para performance."
    )
    indexacao_summary = (
        f"{len(indexacao_findings)} achados de indexação com base em robots, sitemap, noindex e canonical."
        if pages else "Nenhuma página HTML analisada para indexação."
    )
    critical_summary = (
        f"{len(critical_findings)} achados críticos relacionados a erro HTTP, redirect chain, mixed content e limites."
        if pages or critical_findings else "Nenhum erro crítico identificado."
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
        f"Crawl em {len(pages)} páginas HTML; {len(all_findings)} achados relevantes."
        if pages else "Nenhuma página HTML rastreada. Verifique disponibilidade e robots."
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
            "Consolidação de achados por severidade",
            "Status geral por score médio das categorias",
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
            "presença de title de documento",
        ],
        "content": [
            "palavras por página",
            "presença de heading principal",
        ],
        "performance": [
            "TTFB aproximado",
            "tamanho do HTML",
            "numero de recursos referenciados",
            "recursos potencialmente bloqueantes de renderização",
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
        "site_indexado": site_indexado,
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
        "indexado": site_indexado,
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
        worst_pages.append({
            "url": page["url"],
            "status": page["status"],
            "total_issues": total_issues,
            "seo_issues": seo_issues,
            "a11y_issues": a11y_issues,
            "content_issues": content_issues,
            "performance_issues": perf_issues,
            "indexacao_issues": indexacao_issues,
            "critical_issues": critical_issues,
        })
    worst_pages.sort(key=lambda item: item["total_issues"], reverse=True)

    return sections, appendix, worst_pages[:20]


def run_detailed_audit(url: str) -> dict[str, Any]:
    normalized = validate_url(url)
    crawl = crawl_site(
        normalized,
        max_pages=MAX_PAGES,
        max_depth=MAX_DEPTH,
        max_runtime_seconds=MAX_RUNTIME_SECONDS,
        max_link_checks=MAX_LINK_CHECKS,
        per_page_timeout_seconds=PER_PAGE_TIMEOUT_SECONDS,
    )
    sections, appendix, worst_pages = _build_sections(crawl)

    return {
        "url": normalized,
        "generated_at": crawl["generated_at"],
        "crawl": {
            "pages_scanned_html": len(crawl["pages"]),
            "runtime_seconds": crawl["runtime_seconds"],
            "max_pages": MAX_PAGES,
            "max_depth": MAX_DEPTH,
            "max_runtime_seconds": MAX_RUNTIME_SECONDS,
            "per_page_timeout_seconds": PER_PAGE_TIMEOUT_SECONDS,
            "max_link_checks": MAX_LINK_CHECKS,
            "skipped_by_robots": crawl["skipped_by_robots"],
            "non_html_urls_found": crawl["non_html_urls"],
            "limit_notes": crawl["limit_notes"],
            "fetch_errors": crawl["fetch_errors"][:20],
        },
        "sections": sections,
        "worst_pages": worst_pages,
        "appendix": appendix,
    }


