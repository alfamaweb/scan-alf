from __future__ import annotations
import os
import json
from groq import Groq
from dotenv import load_dotenv
load_dotenv()

SYSTEM_PROMPT = """Você é o ALF Scan, um auditor técnico de sites.
Regras:
- Não invente métricas, não crie dados que não estejam no JSON.
- Use linguagem clara, objetiva, sem prometer ranking no Google.
- Priorize ações por impacto (conversão/UX/SEO técnico).
- Sempre cite evidências do JSON (ex: "9 imagens sem alt")."""


def build_user_prompt(result: dict) -> str:
    # Keep it short: LLM should interpret, not re-crawl
    return f"""
Gere um relatório curto para o dono do site com base neste JSON (não invente nada):
{json.dumps(result, ensure_ascii=False, indent=2)}

Formato de saída (exatamente):
RESUMO:
- ...

TOP 3 AÇÕES:
1) ...
2) ...
3) ...

NOTA:
- ...
""".strip()


def generate_summary(result: dict, model: str = "llama-3.1-8b-instant") -> str:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY não encontrada no ambiente.")

    client = Groq(api_key=api_key)

    completion = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(result)},
        ],
        temperature=0.2,
        max_tokens=350,
    )

    return completion.choices[0].message.content.strip()
