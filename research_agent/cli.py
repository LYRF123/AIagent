from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .app_service import ResearchApp
from .agent import ResearchAssistant
from .evaluation import run_evaluation


def emit_json(payload: Any) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.write(b"\n")
        buffer.flush()
        return
    print(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Public-data research assistant agent")
    parser.add_argument("--corpus", default=None, help="Optional path to a corpus JSON file")
    subparsers = parser.add_subparsers(dest="command", required=True)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--top-k", type=int, default=5)

    ask_parser = subparsers.add_parser("ask")
    ask_parser.add_argument("--question", required=True)
    ask_parser.add_argument("--top-k", type=int, default=5)
    ask_parser.add_argument("--session-id", default=None)
    ask_parser.add_argument("--allow-ungrounded", action="store_true")

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--ids", nargs="*")
    compare_parser.add_argument("--query")
    compare_parser.add_argument("--focus", default="methods, findings, and limitations")

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--topic", required=True)
    review_parser.add_argument("--top-k", type=int, default=5)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--eval-path", default=None)
    eval_parser.add_argument("--top-k", type=int, default=5)
    eval_parser.add_argument("--ragas", action="store_true", help="Run optional Ragas LLM-as-judge metrics")
    eval_parser.add_argument("--include-imported", action="store_true", help="Include locally imported documents during evaluation")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "eval":
        include_imported = args.include_imported
    else:
        include_imported = True
    agent = ResearchAssistant(corpus_path=args.corpus, include_imported=include_imported)
    app = ResearchApp(agent=agent)

    if args.command == "search":
        payload = agent.search_papers(args.query, top_k=args.top_k)
    elif args.command == "ask":
        payload = app.ask(
            args.question,
            top_k=args.top_k,
            session_id=args.session_id,
            strict_grounded=not args.allow_ungrounded,
        ).model_dump()
    elif args.command == "compare":
        payload = agent.compare_papers(paper_ids=args.ids, query=args.query, focus=args.focus).model_dump()
    elif args.command == "review":
        payload = agent.generate_review(args.topic, top_k=args.top_k).model_dump()
    else:
        payload = run_evaluation(agent, eval_path=args.eval_path, top_k=args.top_k, use_ragas=args.ragas)

    emit_json(payload)


if __name__ == "__main__":
    main()
