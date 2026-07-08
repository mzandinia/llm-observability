"""Instrumented agent with per-step OTel spans + online eval metrics."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# Import from sibling project (when installed as package or PYTHONPATH)
import sys

CAREER_ROOT = Path(__file__).resolve().parents[1]
AGENT_SRC = CAREER_ROOT.parent / "project2-agentic-incident-assistant" / "src"
if str(AGENT_SRC) not in sys.path:
    sys.path.insert(0, str(AGENT_SRC))

from advanced_evals import evaluate_case, run_advanced_evals
from agent import ask
from evals import load_cases
from hybrid_rag import HybridRAG


def init_tracer(service_name: str = "llm-observability", *, console: bool = True) -> trace.Tracer:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if console:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
    # OTLP export: set OTEL_EXPORTER_OTLP_ENDPOINT to k8s lab collector
    endpoint = __import__("os").getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
            )
        except ImportError:
            pass
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)


@dataclass
class OnlineEvalRecord:
    question: str
    faithfulness: float
    context_recall: float
    latency_ms: float
    tools_used: list[str] = field(default_factory=list)
    passed: bool = False


class InstrumentedAgent:
    def __init__(self, runbooks_dir: Path, tracer: Optional[trace.Tracer] = None):
        self.rag = HybridRAG(runbooks_dir)
        self.rag.index()
        self.tracer = tracer or init_tracer()
        self.online_evals: list[OnlineEvalRecord] = []

    def ask_traced(self, question: str, *, use_mock: bool = True) -> dict:
        start = time.perf_counter()
        with self.tracer.start_as_current_span("agent.ask") as root:
            root.set_attribute("question", question[:120])

            with self.tracer.start_as_current_span("rag.retrieve_hybrid") as span:
                hits = self.rag.retrieve_hybrid(question, k=5)
                span.set_attribute("hit_count", len(hits))
                span.set_attribute("top_source", hits[0]["source"] if hits else "")

            with self.tracer.start_as_current_span("llm.generate"):
                resp = ask(question, self.rag, use_mock=use_mock)

            if resp.tools_used:
                with self.tracer.start_as_current_span("tools.execute") as span:
                    span.set_attribute("tools", ",".join(resp.tools_used))

        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "answer": resp.answer,
            "sources": resp.sources,
            "tools_used": resp.tools_used,
            "latency_ms": round(latency_ms, 1),
            "model": resp.model,
        }

    def run_online_eval(self, cases_path: Path, *, use_mock: bool = True) -> dict:
        cases = load_cases(cases_path)
        self.online_evals = []
        with self.tracer.start_as_current_span("eval.batch") as batch:
            batch.set_attribute("case_count", len(cases))
            for case in cases:
                with self.tracer.start_as_current_span("eval.case") as span:
                    span.set_attribute("case_id", case.id)
                    start = time.perf_counter()
                    result = evaluate_case(case, self.rag, use_mock=use_mock)
                    latency = (time.perf_counter() - start) * 1000
                    rec = OnlineEvalRecord(
                        question=case.question,
                        faithfulness=result["metrics"]["faithfulness"],
                        context_recall=result["metrics"]["context_recall"],
                        latency_ms=round(latency, 1),
                        tools_used=[],
                        passed=result["passed"],
                    )
                    self.online_evals.append(rec)
                    span.set_attribute("passed", result["passed"])
                    span.set_attribute("faithfulness", result["metrics"]["faithfulness"])

        passed = sum(1 for r in self.online_evals if r.passed)
        return {
            "total": len(self.online_evals),
            "passed": passed,
            "pass_rate": round(passed / len(self.online_evals), 3) if self.online_evals else 0,
            "avg_faithfulness": round(
                sum(r.faithfulness for r in self.online_evals) / len(self.online_evals), 3
            ) if self.online_evals else 0,
            "avg_latency_ms": round(
                sum(r.latency_ms for r in self.online_evals) / len(self.online_evals), 1
            ) if self.online_evals else 0,
            "records": [r.__dict__ for r in self.online_evals],
        }


def export_prometheus_text(records: list[OnlineEvalRecord]) -> str:
    """Simple Prometheus exposition for online evals."""
    if not records:
        return "# no eval records\n"
    passed = sum(1 for r in records if r.passed)
    faith = sum(r.faithfulness for r in records) / len(records)
    lat = sum(r.latency_ms for r in records) / len(records)
    lines = [
        "# HELP llm_eval_pass_rate Online eval pass rate",
        "# TYPE llm_eval_pass_rate gauge",
        f"llm_eval_pass_rate {passed / len(records):.3f}",
        "# HELP llm_eval_faithfulness_mean Mean faithfulness score",
        "# TYPE llm_eval_faithfulness_mean gauge",
        f"llm_eval_faithfulness_mean {faith:.3f}",
        "# HELP llm_eval_latency_ms_mean Mean eval latency ms",
        "# TYPE llm_eval_latency_ms_mean gauge",
        f"llm_eval_latency_ms_mean {lat:.1f}",
    ]
    return "\n".join(lines) + "\n"
