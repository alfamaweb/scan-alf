def run_basic_checks(page: dict) -> list[dict]:
    findings: list[dict] = []

    status = page.get("status", 0)
    if status >= 400 or status == 0:
        findings.append({
            "id": "http_status_bad",
            "severity": "HIGH",
            "message": f"Pagina retornou status HTTP {status}."
        })

    title = page.get("title")
    if not title or len(title.strip()) < 10:
        findings.append({
            "id": "title_missing_or_short",
            "severity": "HIGH",
            "message": "Title ausente ou muito curto (SEO e contexto da pagina)."
        })
    elif len(title) > 60:
        findings.append({
            "id": "title_too_long",
            "severity": "LOW",
            "message": f"Title possivelmente longo demais ({len(title)} chars)."
        })

    if not page.get("meta_description"):
        findings.append({
            "id": "meta_description_missing",
            "severity": "MED",
            "message": "Meta description ausente (impacta snippet/CTR)."
        })
    elif len(page["meta_description"]) > 160:
        findings.append({
            "id": "meta_description_too_long",
            "severity": "LOW",
            "message": f"Meta description possivelmente longa ({len(page['meta_description'])} chars)."
        })

    missing_alt = page.get("images_missing_alt", 0)
    if missing_alt > 0:
        findings.append({
            "id": "images_missing_alt",
            "severity": "MED",
            "message": f"{missing_alt} imagens sem alt (acessibilidade e contexto)."
        })

    links_total = page.get("links_total", 0)
    if links_total == 0:
        findings.append({
            "id": "no_links_found",
            "severity": "LOW",
            "message": "Nenhum link encontrado na pagina."
        })

    return findings
