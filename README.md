# Scan Alf API

API simples de auditoria com **entrada unica**:

```json
{
  "url": "https://example.com"
}
```

## Endpoints

1. `POST /analyze_summary`
2. `POST /report`


## Setup local

```bash
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

B