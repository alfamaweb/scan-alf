def compute_scores(findings: list[dict]) -> dict:
    scores = {
        "overall": 100,
        "SEO": 100,
        "A11Y": 100,
        "CONTENT": 100
    }

    penalty = {"HIGH": 20, "MED": 10, "LOW": 4}

    category_map = {
        "http_status_bad": "CONTENT",
        "title_missing_or_short": "SEO",
        "title_too_long": "SEO",
        "meta_description_missing": "SEO",
        "meta_description_too_long": "SEO",
        "images_missing_alt": "A11Y",
        "no_links_found": "CONTENT",
    }

    for f in findings:
        sev = f.get("severity", "LOW")
        p = penalty.get(sev, 4)
        cat = category_map.get(f.get("id", ""), "CONTENT")

        scores["overall"] = max(0, scores["overall"] - p)
        scores[cat] = max(0, scores[cat] - p)

    return scores
