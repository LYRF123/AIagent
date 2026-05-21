import json
import threading

import pytest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

from daidainiao_agent.models import EvalCase, Evidence
from daidainiao_agent.rag_lab import calculate_retrieval_metrics, normalize_lab_configs, run_rag_lab_evaluation
from daidainiao_agent.server import Handler, set_app


def make_evidence(paper_id: str, text: str, score: float = 0.8) -> Evidence:
    return Evidence(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        section="summary",
        text=text,
        score=score,
    )


def test_rag_lab_metrics_calculate_retrieval_quality() -> None:
    case = EvalCase(
        case_id="case-1",
        question="Which papers discuss retrieval and critique?",
        expected_paper_ids=["target-a", "target-b"],
        expected_keywords=["retrieval", "critique"],
    )
    evidence = [
        make_evidence("other", "unrelated planning note"),
        make_evidence("target-a", "retrieval appears in this passage"),
        make_evidence("target-b", "the critique signal appears later"),
    ]

    metrics = calculate_retrieval_metrics(case, evidence)

    assert metrics["hit_at_k"] == 1.0
    assert metrics["recall_like_at_k"] == 1.0
    assert metrics["mrr"] == 0.5
    assert metrics["keyword_coverage"] == 1.0
    assert metrics["expected_best_rank"] == 2


def test_rag_lab_configs_accept_frontend_shape_and_rerank_alias() -> None:
    configs = normalize_lab_configs(
        [
            {"name": "rerank_on", "top_k": 2, "candidate_k": 8, "use_rerank": True},
            {"name": "rerank_off", "top_k": 2, "candidate_k": 8, "rerank": False},
        ]
    )

    assert [config.config_id for config in configs] == ["rerank_on", "rerank_off"]
    assert [config.use_rerank for config in configs] == [True, False]


@pytest.mark.slow
def test_rag_lab_evaluation_compares_rerank_modes(daidainiao_agent, monkeypatch) -> None:
    calls = []

    def fake_search(query: str, top_k: int = 5, candidate_k: int = 12, use_rerank: bool = True):
        calls.append(
            {
                "query": query,
                "top_k": top_k,
                "candidate_k": candidate_k,
                "use_rerank": use_rerank,
            }
        )
        if use_rerank:
            evidence = [make_evidence("react", "reasoning actions observations", score=0.95)]
            tool = "dashscope_rerank"
        else:
            evidence = [make_evidence("other", "reasoning only", score=0.45)]
            tool = "fusion_rank"
        return SimpleNamespace(
            evidence=evidence,
            trace=[{"tool": tool, "input": query, "output": evidence[0].paper_id}],
            rerank_failed=False,
        )

    daidainiao_agent.llm.api_key = "fake-key"
    monkeypatch.setattr(daidainiao_agent.hybrid_retriever, "search", fake_search)

    payload = run_rag_lab_evaluation(
        daidainiao_agent,
        cases=[
            {
                "case_id": "qa-rerank",
                "question": "How does ReAct combine reasoning with actions?",
                "expected_paper_ids": ["react"],
                "expected_keywords": ["reasoning", "actions"],
            }
        ],
        configs=[
            {"config_id": "fusion", "top_k": 1, "candidate_k": 3, "use_rerank": False},
            {"config_id": "rerank", "top_k": 1, "candidate_k": 3, "use_rerank": True},
        ],
    )

    assert [call["use_rerank"] for call in calls] == [False, True]
    assert payload["configs"][0]["use_rerank"] is False
    assert payload["configs"][1]["use_rerank"] is True
    assert payload["summary"][0]["hit_at_k"] == 0.0
    assert payload["summary"][1]["hit_at_k"] == 1.0
    assert payload["per_case"][0]["results"][1]["rerank_enabled"] is True
    assert payload["per_case"][0]["results"][1]["ranked_ids"] == ["react"]
    rerank_result = payload["per_case"][0]["results"][1]
    flight_recorder = rerank_result["flight_recorder"]
    stage_names = [stage["name"] for stage in flight_recorder["stages"]]
    assert flight_recorder["original_question"] == "How does ReAct combine reasoning with actions?"
    assert flight_recorder["config"]["config_id"] == "rerank"
    assert stage_names[:3] == ["query_expansion", "tfidf", "bm25"]
    assert "fusion" in stage_names
    assert "rerank" in stage_names
    assert flight_recorder["stages"][-1]["top"][0]["paper_id"] == "react"
    courtroom = payload["per_case"][0]["rerank_courtroom"][0]
    assert courtroom["verdict"] == "helped"
    assert courtroom["expected_rank_before"] is None
    assert courtroom["expected_rank_after"] == 1
    assert courtroom["rank_delta"] == 1
    assert courtroom["mrr_delta"] == 1.0
    assert rerank_result["rerank_courtroom"] == courtroom
    assert payload["per_case"][0]["results"][0]["failure_reasons"] == ["retrieval_miss"]
    assert rerank_result["failure_reasons"] == []
    assert payload["failures"][0]["config_id"] == "fusion"


def test_rag_lab_failure_lens_marks_rerank_and_context_noise(daidainiao_agent, monkeypatch) -> None:
    def fake_search(query: str, top_k: int = 5, candidate_k: int = 12, use_rerank: bool = True):
        if "hurt" in query and use_rerank:
            evidence = [make_evidence("other", "unrelated text", score=0.9)]
            tool = "dashscope_rerank"
        elif "hurt" in query:
            evidence = [make_evidence("target", "alpha signal", score=0.8)]
            tool = "fusion_rank"
        elif "no gain" in query:
            evidence = [make_evidence("target", "alpha signal", score=0.8)]
            tool = "dashscope_rerank" if use_rerank else "fusion_rank"
        else:
            evidence = [
                make_evidence("other", "distracting preface", score=0.9),
                make_evidence("target", "alpha signal", score=0.8),
                make_evidence("noise", "distracting appendix", score=0.7),
            ][:top_k]
            tool = "fusion_rank"
        return SimpleNamespace(
            evidence=evidence,
            trace=[{"tool": tool, "input": query, "output": ", ".join(item.paper_id for item in evidence)}],
            rerank_failed=False,
        )

    daidainiao_agent.llm.api_key = "fake-key"
    monkeypatch.setattr(daidainiao_agent.hybrid_retriever, "search", fake_search)

    payload = run_rag_lab_evaluation(
        daidainiao_agent,
        cases=[
            {
                "case_id": "hurt",
                "question": "hurt rerank case",
                "expected_paper_ids": ["target"],
                "expected_keywords": ["alpha"],
            },
            {
                "case_id": "no-gain",
                "question": "no gain rerank case",
                "expected_paper_ids": ["target"],
                "expected_keywords": ["alpha"],
            },
            {
                "case_id": "noise",
                "question": "context noise case",
                "expected_paper_ids": ["target"],
                "expected_keywords": ["alpha"],
            },
        ],
        configs=[
            {"config_id": "fusion", "top_k": 3, "candidate_k": 3, "use_rerank": False},
            {"config_id": "rerank", "top_k": 3, "candidate_k": 3, "use_rerank": True},
        ],
    )

    by_case = {item["case_id"]: item for item in payload["per_case"]}
    hurt_rerank = by_case["hurt"]["results"][1]
    assert by_case["hurt"]["rerank_courtroom"][0]["verdict"] == "hurt"
    assert {"retrieval_miss", "low_keyword_coverage", "rerank_hurt"}.issubset(hurt_rerank["failure_reasons"])

    no_gain_rerank = by_case["no-gain"]["results"][1]
    assert by_case["no-gain"]["rerank_courtroom"][0]["verdict"] == "no_op"
    assert no_gain_rerank["failure_reasons"] == ["rerank_no_gain"]

    noise_fusion = by_case["noise"]["results"][0]
    assert noise_fusion["expected_best_rank"] == 2
    assert noise_fusion["failure_reasons"] == ["context_noise"]


def test_rag_lab_http_endpoint_returns_structured_json(app_service, monkeypatch) -> None:
    def fake_search(query: str, top_k: int = 5, candidate_k: int = 12, use_rerank: bool = True):
        return SimpleNamespace(
            evidence=[make_evidence("react", "ReAct combines reasoning and actions.")],
            trace=[{"tool": "fusion_rank", "input": query, "output": "react"}],
            rerank_failed=False,
        )

    monkeypatch.setattr(app_service.agent.hybrid_retriever, "search", fake_search)
    set_app(app_service)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    conn = HTTPConnection("127.0.0.1", server.server_port, timeout=5)

    try:
        body = json.dumps(
            {
                "cases": [
                    {
                        "case_id": "qa-http",
                        "question": "How does ReAct combine reasoning with actions?",
                        "expected_paper_ids": ["react"],
                        "expected_keywords": ["reasoning", "actions"],
                    }
                ],
                "configs": [
                    {"config_id": "fusion", "top_k": 1, "candidate_k": 2, "use_rerank": False}
                ],
            }
        )
        conn.request(
            "POST",
            "/rag-lab/evaluate",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        response = conn.getresponse()
        data = json.loads(response.read().decode("utf-8"))

        assert response.status == 200
        assert data["configs"][0]["config_id"] == "fusion"
        assert data["summary"][0]["hit_at_k"] == 1.0
        assert data["per_case"][0]["results"][0]["expected_best_rank"] == 1
        assert data["per_case"][0]["results"][0]["flight_recorder"]["config"]["config_id"] == "fusion"
        assert data["per_case"][0]["results"][0]["failure_reasons"] == []
        assert data["failures"] == []
    finally:
        conn.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
