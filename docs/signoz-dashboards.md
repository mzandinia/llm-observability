# SigNoz dashboards for LLM observability

## Trace filters

| Filter | Value |
|--------|-------|
| Service | `llm-observability` |
| Span name | `rag.retrieve_hybrid`, `llm.generate`, `tools.execute`, `eval.case` |

## Useful panels

1. **P95 latency by span** — group by `span.name`, aggregate p95 duration
2. **Retrieval hit rate** — `hit_count` attribute on `rag.retrieve_hybrid`
3. **Eval pass rate over time** — `passed` attribute on `eval.case`
4. **Faithfulness trend** — `faithfulness` attribute on `eval.case`

## Import Grafana dashboard

```bash
# With Grafana from k8s-observability-lab or project2 observability stack
curl -X POST http://admin:admin@localhost:3000/api/dashboards/db \
  -H "Content-Type: application/json" \
  -d @dashboards/grafana-llm-observability.json
```

## OTLP endpoint (lab)

```bash
kubectl port-forward -n signoz svc/signoz-otel-collector 4317:4317
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
python src/main.py --eval
```
