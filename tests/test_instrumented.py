import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
AGENT_SRC = ROOT.parent / "project2-agentic-incident-assistant" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(AGENT_SRC))

from instrumented_agent import InstrumentedAgent, export_prometheus_text, init_tracer

RUNBOOKS = ROOT.parent / "project2-agentic-incident-assistant" / "data" / "runbooks"
EVALS = ROOT.parent / "project2-agentic-incident-assistant" / "evals" / "test_cases.json"


@pytest.fixture
def agent():
    return InstrumentedAgent(RUNBOOKS, tracer=init_tracer(console=False))


def test_ask_traced(agent):
    result = agent.ask_traced("Why is ingest spike on web-app-index?", use_mock=True)
    assert "answer" in result
    assert result["latency_ms"] > 0
    assert "web-app" in result["answer"].lower()


def test_online_eval(agent):
    report = agent.run_online_eval(EVALS, use_mock=True)
    assert report["total"] == 20
    assert report["pass_rate"] >= 0.7
    assert report["avg_faithfulness"] > 0


def test_prometheus_export(agent):
    agent.run_online_eval(EVALS, use_mock=True)
    body = export_prometheus_text(agent.online_evals)
    assert "llm_eval_pass_rate" in body
    assert "llm_eval_faithfulness_mean" in body
