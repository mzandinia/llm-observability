"""CLI + minimal API for LLM observability."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from instrumented_agent import InstrumentedAgent, export_prometheus_text, init_tracer

RUNBOOKS = Path(__file__).resolve().parents[1].parent / "project2-agentic-incident-assistant" / "data" / "runbooks"
EVALS = Path(__file__).resolve().parents[1].parent / "project2-agentic-incident-assistant" / "evals" / "test_cases.json"

app = FastAPI(title="LLM Observability", version="1.0.0")
_agent: InstrumentedAgent | None = None


@app.on_event("startup")
def startup():
    global _agent
    if RUNBOOKS.exists():
        _agent = InstrumentedAgent(RUNBOOKS, tracer=init_tracer())


@app.get("/health")
def health():
    return {"status": "ok", "agent_ready": _agent is not None}


@app.post("/ask")
def ask(q: str, use_mock: bool = True):
    return _agent.ask_traced(q, use_mock=use_mock)


@app.post("/evals/online")
def online_evals(use_mock: bool = True):
    return _agent.run_online_eval(EVALS, use_mock=use_mock)


@app.get("/metrics")
def metrics():
    if not _agent or not _agent.online_evals:
        return PlainTextResponse("# run POST /evals/online first\n", media_type="text/plain")
    return PlainTextResponse(
        export_prometheus_text(_agent.online_evals), media_type="text/plain"
    )


def main():
    parser = argparse.ArgumentParser(description="LLM Observability CLI")
    parser.add_argument("question", nargs="?", default="Why is ingest spike on web-app-index?")
    parser.add_argument("--eval", action="store_true", help="Run online eval batch")
    parser.add_argument("--mock", action="store_true", default=True)
    args = parser.parse_args()

    if not RUNBOOKS.exists():
        print(f"Runbooks not found: {RUNBOOKS}", file=sys.stderr)
        sys.exit(1)

    agent = InstrumentedAgent(RUNBOOKS, tracer=init_tracer(console=True))
    if args.eval:
        report = agent.run_online_eval(EVALS, use_mock=args.mock)
        print(json.dumps(report, indent=2))
    else:
        print(json.dumps(agent.ask_traced(args.question, use_mock=args.mock), indent=2))


if __name__ == "__main__":
    main()
