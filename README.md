# Scan Alf API

Pipeline de auditoria técnica de sites (crawling + extração + classificação + scoring + relatório JSON), com opção de sumário executivo via LLM e cache pra reduzir custo/latência.:

```json
{
  "url": "https://example.com"
}
```

## Endpoints

1. `POST /analyze_summary`
2. `POST /report`

## Autenticacao 

Todos os endpoints exigem o header `X-API-Token`.

## Arquivo .env

Base recomendada:

```bash
copy .env.example .env
```

No `.env`, configure principalmente:

- `API_TOKEN`: obrigatorio para acesso aos endpoints
- `LLM_API_KEY`: obrigatorio para `POST /analyze_summary`
- `LLM_MODEL`: opcional (para Groq, exemplo: `llama-3.1-8b-instant`)


## Setup local

```bash
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
