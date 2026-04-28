# Scan Alf API

Pipeline de auditoria técnica de sites: crawling, extração de métricas, classificação por severidade, scoring e relatório JSON. Inclui sumário executivo via LLM e cache em memória para reduzir latência em requisições repetidas.

## Endpoints

### `POST /report`

Auditoria completa com crawl profundo (até 150 páginas). Retorna scores por categoria, achados detalhados com evidências, piores páginas e apêndice com métricas brutas.

### `POST /analyze_summary`

Auditoria completa com sumário executivo gerado por LLM. Retorna score, status e um parágrafo consultivo por categoria.

**Body (ambos os endpoints):**
```json
{ "url": "https://example.com" }
```

## Autenticação

Todos os endpoints exigem o header `X-API-Token`:

```
X-API-Token: <seu_token>
```

## Variáveis de ambiente

| Variável | Obrigatório | Descrição |
|---|---|---|
| `API_TOKEN` | Sim | Token de acesso aos endpoints |
| `LLM_API_KEY` | Sim (para `/analyze_summary`) | Chave da API Groq ou OpenAI |
| `LLM_MODEL` | Não | Modelo LLM (padrão: `llama-3.1-8b-instant`) |

## Setup local

```bash
pip install -r requirements.txt
cp .env.example .env   # edite com seus valores
uvicorn main:app --reload --port 8000
```

## Estrutura do projeto

```
audit/
├── constants.py   — constantes e configurações de crawl
├── crawler.py     — crawl do site, parsing HTML, robots.txt
├── analyzer.py    — findings, scores, seções, cache de auditoria
├── llm.py         — integração LLM e frases de fallback
└── report.py      — formatação da resposta JSON em PT-BR
main.py            — endpoints FastAPI
```

## API publicada

**Base URL:** https://analise-site.alfamaweb.com.br/
