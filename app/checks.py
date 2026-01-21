def run_basic_checks(page: dict) -> list[dict]:
    findings: list[dict] = []

    # HTTP status
    status = page.get("status", 0)
    if status >= 400 or status == 0:
        findings.append({
            "id": "http_status_bad",
            "severity": "HIGH",
            "message": f"Página retornou status HTTP {status}."
        })

    # Title
    title = page.get("title")
    if not title or len(title.strip()) < 10:
        findings.append({
            "id": "title_missing_or_short",
            "severity": "HIGH",
            "message": "Title ausente ou muito curto (SEO e contexto da página)."
        })
    elif len(title) > 60:
        findings.append({
            "id": "title_too_long",
            "severity": "LOW",
            "message": f"Title possivelmente longo demais ({len(title)} chars)."
        })

    # Meta description
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

    # Images alt
    missing_alt = page.get("images_missing_alt", 0)
    if missing_alt > 0:
        findings.append({
            "id": "images_missing_alt",
            "severity": "MED",
            "message": f"{missing_alt} imagens sem alt (acessibilidade e contexto)."
        })

    return findings
