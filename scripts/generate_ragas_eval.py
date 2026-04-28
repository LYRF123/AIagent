"""Generate a RAG evaluation set from a local literature folder using ragas TestsetGenerator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langchain_core.documents import Document as LCDocument

from research_agent.file_import import extract_text_from_file, sanitize_slug
from research_agent.llm import (
    DEFAULT_DASHSCOPE_BASE_URL,
    DEFAULT_DASHSCOPE_EMBEDDING_MODEL,
    DEFAULT_DASHSCOPE_MODEL,
    DashScopeEmbeddings,
    resolve_setting,
)
from research_agent.logging_config import logger
from research_agent.models import Paper

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt"}


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def compact_text(value: str, limit: int = 12000) -> str:
    compact = " ".join(value.replace("\x00", " ").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def iter_source_files(input_dir: Path, max_docs: int = 0) -> list[Path]:
    paths = sorted(
        [p for p in input_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES],
        key=lambda p: str(p).lower(),
    )
    if max_docs > 0:
        paths = paths[:max_docs]
    return paths


def unique_paper_id(path: Path, used_ids: set[str]) -> str:
    base = sanitize_slug(path.stem)
    paper_id = base
    index = 2
    while paper_id in used_ids:
        paper_id = f"{base}-{index}"
        index += 1
    used_ids.add(paper_id)
    return paper_id


def build_paper(path: Path, text: str, used_ids: set[str]) -> Paper:
    import re
    title = re.sub(r"[_\-]+", " ", path.stem)
    title = " ".join(title.split()) or path.stem
    topics = []
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9\-]{2,}", f"{title} {text[:1200]}".lower()):
        normalized = token.strip("-")
        if len(normalized) >= 3 and normalized not in topics:
            topics.append(normalized)
        if len(topics) >= 8:
            break
    return Paper(
        paper_id=unique_paper_id(path, used_ids),
        title=title,
        year=0,
        venue="Local Literature Folder",
        authors=["Local Document"],
        source_url=str(path),
        topics=topics,
        summary=compact_text(text, limit=12000),
        methods=[],
        findings=[],
        limitations=[],
    )


# ---------------------------------------------------------------------------
# Core: use ragas TestsetGenerator
# ---------------------------------------------------------------------------

def generate_testset(
    papers: list[tuple[Paper, str]],
    testset_size: int,
    api_key: str,
    base_url: str,
    model: str,
    embedding_model: str,
) -> list[dict]:
    """Use ragas TestsetGenerator to produce evaluation samples."""
    from langchain_openai import ChatOpenAI
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.testset import TestsetGenerator

    # Build LangChain documents from parsed papers
    lc_docs: list[LCDocument] = []
    for paper, text in papers:
        lc_docs.append(
            LCDocument(
                page_content=compact_text(text, limit=12000),
                metadata={
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "source": paper.source_url,
                },
            )
        )

    # Wrap DashScope-compatible models for ragas
    chat_model = ChatOpenAI(
        model_name=model,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0.2,
        max_retries=2,
        request_timeout=120,
    )
    embeddings = DashScopeEmbeddings(
        api_key=api_key,
        base_url=base_url,
        model=embedding_model,
    )

    generator = TestsetGenerator(
        llm=LangchainLLMWrapper(chat_model),
        embedding_model=LangchainEmbeddingsWrapper(embeddings),
    )

    testset = generator.generate_with_langchain_docs(
        documents=lc_docs,
        testset_size=testset_size,
        raise_exceptions=False,
    )

    return testset.to_list()


def ragas_sample_to_eval_case(sample: dict, index: int) -> dict:
    """Convert a ragas testset sample dict to the project's EvalCase format."""
    user_input = sample.get("user_input", "")
    reference = sample.get("reference", "")
    reference_contexts = sample.get("reference_contexts") or []

    # Extract keywords from reference text
    import re
    words = re.findall(r"[a-zA-Z\u4e00-\u9fff]{3,}", reference.lower())
    # Deduplicate while preserving order
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        if w not in seen:
            seen.add(w)
            keywords.append(w)
        if len(keywords) >= 6:
            break

    # Try to extract paper_id from reference_contexts metadata (not always available)
    paper_ids: list[str] = []

    synthesizer = sample.get("synthesizer_name", "ragas")
    tags = [synthesizer] if synthesizer else ["ragas"]

    return {
        "case_id": f"ragas-gen:{index:03d}",
        "question": user_input,
        "expected_paper_ids": paper_ids,
        "expected_keywords": keywords,
        "reference": reference,
        "tags": tags,
    }


# ---------------------------------------------------------------------------
# Fallback: heuristic generation when no API key
# ---------------------------------------------------------------------------

def fallback_cases(paper: Paper, text: str, cases_per_doc: int, language: str) -> list[dict]:
    reference = compact_text(text, limit=700)
    keywords = paper.topics[:5] or [paper.title.split()[0].lower()]
    if language == "zh":
        question = f"{paper.title} 这篇论文的主要研究内容是什么？"
    else:
        question = f"What is the main research idea of {paper.title}?"
    return [
        {
            "case_id": f"{paper.paper_id}:qa-{i:02d}",
            "question": question,
            "expected_paper_ids": [paper.paper_id],
            "expected_keywords": keywords,
            "reference": reference,
            "tags": ["single-hop", "summary"],
        }
        for i in range(1, cases_per_doc + 1)
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a local RAG evaluation set from a literature folder.")
    parser.add_argument("--input-dir", required=True, help="Folder containing PDF, DOCX, or TXT papers")
    parser.add_argument("--output-corpus", default="data/literature_papers.json")
    parser.add_argument("--output-eval", default="data/literature_eval.json")
    parser.add_argument("--max-corpus-docs", type=int, default=60, help="Maximum documents to parse into corpus; 0 means all")
    parser.add_argument("--max-eval-docs", type=int, default=15, help="Maximum parsed documents to use for generated eval cases")
    parser.add_argument("--cases-per-doc", type=int, default=2, help="Cases per doc (used for testset_size calculation and fallback)")
    parser.add_argument("--language", choices=["en", "zh"], default="en")
    parser.add_argument("--no-llm", action="store_true", help="Use heuristic cases instead of ragas TestsetGenerator")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    source_files = iter_source_files(input_dir, max_docs=args.max_corpus_docs)

    # Parse documents
    used_ids: set[str] = set()
    parsed_items: list[tuple[Paper, str]] = []
    skipped = []
    for path in source_files:
        try:
            text = extract_text_from_file(path)
            if len(compact_text(text, limit=2000)) < 600:
                skipped.append({"path": str(path), "reason": "too little extracted text"})
                continue
            paper = build_paper(path, text, used_ids)
            parsed_items.append((paper, text))
            logger.info(f"parsed: {paper.paper_id} :: {paper.title}")
        except Exception as exc:
            skipped.append({"path": str(path), "reason": str(exc)})
            logger.warning(f"skipped: {path} :: {exc}")

    # Write corpus
    papers_data = [paper.model_dump() for paper, _ in parsed_items]
    output_corpus = Path(args.output_corpus)
    output_corpus.parent.mkdir(parents=True, exist_ok=True)
    output_corpus.write_text(json.dumps(papers_data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"corpus written: {output_corpus} ({len(papers_data)} documents)")

    # Generate eval cases
    eval_items = parsed_items[: args.max_eval_docs]
    api_key = resolve_setting("DASHSCOPE_API_KEY")

    if api_key and not args.no_llm:
        # Use ragas TestsetGenerator
        base_url = (resolve_setting("DASHSCOPE_BASE_URL", default=DEFAULT_DASHSCOPE_BASE_URL) or DEFAULT_DASHSCOPE_BASE_URL).rstrip("/")
        model = resolve_setting("DASHSCOPE_MODEL", default=DEFAULT_DASHSCOPE_MODEL) or DEFAULT_DASHSCOPE_MODEL
        embedding_model = resolve_setting("DASHSCOPE_EMBEDDING_MODEL", default=DEFAULT_DASHSCOPE_EMBEDDING_MODEL) or DEFAULT_DASHSCOPE_EMBEDDING_MODEL
        testset_size = len(eval_items) * args.cases_per_doc

        logger.info(f"generating {testset_size} eval cases with ragas TestsetGenerator ...")
        try:
            raw_samples = generate_testset(
                papers=eval_items,
                testset_size=testset_size,
                api_key=api_key,
                base_url=base_url,
                model=model,
                embedding_model=embedding_model,
            )
            eval_cases = [
                ragas_sample_to_eval_case(sample, i)
                for i, sample in enumerate(raw_samples, start=1)
            ]
        except Exception as exc:
            logger.warning(f"ragas generation failed, falling back to heuristic: {exc}")
            eval_cases = []
            for paper, text in eval_items:
                eval_cases.extend(fallback_cases(paper, text, args.cases_per_doc, args.language))
    else:
        # Fallback: heuristic
        logger.info("no DASHSCOPE_API_KEY or --no-llm, using heuristic fallback ...")
        eval_cases = []
        for paper, text in eval_items:
            eval_cases.extend(fallback_cases(paper, text, args.cases_per_doc, args.language))

    # Write eval cases
    output_eval = Path(args.output_eval)
    output_eval.parent.mkdir(parents=True, exist_ok=True)
    output_eval.write_text(json.dumps(eval_cases, ensure_ascii=False, indent=2), encoding="utf-8")

    report = {
        "input_dir": str(input_dir),
        "source_files": len(source_files),
        "parsed_documents": len(parsed_items),
        "skipped_documents": len(skipped),
        "eval_cases": len(eval_cases),
        "output_corpus": str(output_corpus),
        "output_eval": str(output_eval),
        "ragas_generation": bool(api_key and not args.no_llm),
        "skipped": skipped[:20],
    }
    logger.info(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
