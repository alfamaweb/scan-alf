# Scan Alf API

API simples de auditoria com **entrada unica**:

```json
{
  "url": "https://example.com"
}
```

## Endpoints

1. `POST /analyze_summary`
- Retorna resumo executivo com uma frase por categoria.
- Reaproveita dados em cache da analise inicial quando disponivel.
- Se nao houver cache, roda perfil rapido de auditoria para responder mais cedo.

2. `POST /report`
- Retorna **JSON detalhado** (nao gera PDF).
- Estrutura organizada em portugues: resumo executivo, secoes, piores paginas e apendice.
- Reaproveita cache quando disponivel.

## Setup local

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Base local:

```text
http://localhost:8000
```

## Exemplo Postman

Use o mesmo body nos dois endpoints:

```json
{
  "url": "https://example.com"
}
```

## Regras e limites

- Mesmo dominio e mesmo protocolo (same-origin)
- Apenas paginas HTML entram na auditoria
- Respeita `robots.txt`
- Limites completos:
  - `MAX_PAGES = 150`
  - `MAX_DEPTH = 6`
  - `MAX_RUNTIME_SECONDS = 120`
  - `PER_PAGE_TIMEOUT_SECONDS = 20`
- Limites do perfil rapido de resumo:
  - `SUMMARY_MAX_PAGES = 12`
  - `SUMMARY_MAX_DEPTH = 1`
  - `SUMMARY_MAX_RUNTIME_SECONDS = 8`
  - `SUMMARY_PER_PAGE_TIMEOUT_SECONDS = 5`

## Cache em memoria

- Cache de auditoria detalhada: `AUDIT_CACHE_TTL_SECONDS = 900`
- Cache de resumo executivo: `SUMMARY_CACHE_TTL_SECONDS = 600`

## LLM opcional

Se `LLM_API_KEY` existir:
- o resumo executivo pode usar LLM para refinar a frase final
- sem inventar fatos
- fallback deterministico automatico em caso de erro
