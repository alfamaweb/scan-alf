from __future__ import annotations

from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def _fmt(value: object, fallback: str = "-") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _pdf_safe(text: str) -> str:
    return text.encode("latin-1", "ignore").decode("latin-1")


def build_pdf_report(result: dict, output_path: str) -> str:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    body_style = styles["BodyText"]
    body_style.leading = 14

    elements = []
    elements.append(Paragraph("AlfamaWeb", title_style))
    elements.append(Spacer(1, 10))

    input_data = result.get("input", {})
    meta = result.get("meta", {})
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    elements.append(Paragraph(f"URL analisada: {escape(_fmt(input_data.get('url')))}", body_style))
    elements.append(Paragraph(f"Modo: {_fmt(input_data.get('mode'))}", body_style))
    elements.append(Paragraph(f"Paginas analisadas: {_fmt(meta.get('pages_scanned'))}", body_style))
    elements.append(Paragraph(f"Gerado em: {timestamp}", body_style))
    elements.append(Spacer(1, 12))

    report_text = _fmt(result.get("report") or result.get("summary"), fallback="")
    if report_text:
        elements.append(Paragraph("Relatorio", styles["Heading2"]))
        for line in _lines(report_text):
            elements.append(Paragraph(escape(_pdf_safe(line)), body_style))
        elements.append(Spacer(1, 12))

    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    doc.build(elements)
    return str(output)
