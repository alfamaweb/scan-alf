from __future__ import annotations

from pathlib import Path

from app.engine.report_generator import generate_report


def _sample_result() -> dict:
    return {
        "input": {"url": "https://residencial-parque.com"},
        "pages": [
            {
                "url": "https://residencial-parque.com/",
                "title": "Residencial Parque - Lotes em Condominio",
                "h1_text": "Lotes amplos com infraestrutura completa",
                "meta_description": None,
                "page_size_kb": 980.5,
                "images_total": 18,
                "lazy_loading_present": False,
                "render_blocking_scripts": 2,
                "cdn_hints": False,
                "has_viewport": True,
                "has_canonical": False,
                "has_schema": False,
                "has_og": False,
                "indexable": True,
                "h1_count": 1,
                "nav_items": ["Home", "Empreendimento", "Localizacao", "Contato"],
                "cta_texts": ["Fale com um consultor", "Agende uma visita"],
                "has_form": True,
                "has_whatsapp": True,
                "has_faq": False,
                "has_gallery": False,
                "has_testimonials": False,
                "has_pricing": False,
                "has_numbers": True,
                "number_samples": ["120", "250"],
                "word_count": 180,
                "section_count": 2,
                "images_missing_alt": 5,
                "is_real_estate": True,
            }
        ],
        "diagnostics": {"duplicate_home": True},
        "scores": {"overall": 72, "SEO": 58, "A11Y": 84, "CONTENT": 66},
        "context": {
            "brand_name": "Residencial Parque",
            "segment": "Loteamento",
            "city": "Goiania - GO",
            "product": "Lotes residenciais",
            "consultancy": "ALF Scan",
            "differentiators": ["Infraestrutura completa", "Localizacao privilegiada"],
            "social": ["@residencialparque"],
        },
    }


def test_report_golden_snapshot():
    report = generate_report(_sample_result())
    expected = (Path(__file__).parent / "fixtures" / "golden_report.txt").read_text(encoding="utf-8")
    report = report.replace("\r\n", "\n").strip()
    expected = expected.replace("\r\n", "\n").strip()
    assert report == expected
    assert "DIAGN\u00d3STICO CONSOLIDADO" in report
    assert "SEO ON-PAGE" in report
    assert "Consultoria: AlfamaWeb" not in report


def test_missing_data_outputs_required_phrases():
    report = generate_report({"input": {"url": "https://exemplo.com"}, "pages": []})
    assert "Sem evidencias de mensagem aspiracional; requer validacao." in report
    assert "Requer validacao" in report


def test_duplicate_home_flagged_as_critical():
    result = {
        "input": {"url": "https://exemplo.com"},
        "pages": [{"url": "https://exemplo.com/", "title": "Home"}],
        "diagnostics": {"duplicate_home": True},
    }
    report = generate_report(result)
    assert "PROBLEMA CR\u00cdTICO: Conteudo duplicado entre / e /home." in report
