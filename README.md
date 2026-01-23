# ALF Scan

ALF Scan e um analisador de sites. Ele coleta dados basicos,
gera achados, calcula scores e cria um PDF com o relatorio.

## Rodando a API

```bash
playwright install
uvicorn app.api:app --reload
http://localhost:8000/
```

## Report Output Format

O output final da analise e um relatorio textual com secoes fixas:
- Capa
- Visao geral do site
- Performance tecnica
- SEO on-page
- Experiencia do usuario
- Acessibilidade
- Conversao e comunicacao
- Pontos fortes
- Gargalos criticos
- Oportunidades estrategicas
- Diagnostico consolidado

O endpoint `/analyze` devolve o texto completo em `report`, pronto para uso.

## Tests

```bash
pytest
```
