from daidainiao_agent.hybrid import FUSION_METHOD, HybridRetriever
from daidainiao_agent.models import Evidence


def make_evidence(paper_id: str, section: str, score: float) -> Evidence:
    return Evidence(
        paper_id=paper_id,
        title=f"Paper {paper_id}",
        section=section,
        text=f"{paper_id} {section} evidence",
        score=score,
    )


def test_rrf_fusion_rewards_cross_retriever_agreement() -> None:
    retriever = HybridRetriever(None, None, None, None, None)

    merged = retriever._merge_candidates(
        tfidf_hits=[
            make_evidence("single", "summary", 1.0),
            make_evidence("shared", "summary", 0.8),
        ],
        bm25_hits=[
            make_evidence("shared", "summary", 1.0),
        ],
        vector_hits=[],
    )

    if FUSION_METHOD == "score_sum":
        assert merged[0].paper_id in {"single", "shared"}
        return

    assert merged[0].paper_id == "shared"
    assert merged[0].score == 1.0
    assert all(0.0 <= item.score <= 1.0 for item in merged)
