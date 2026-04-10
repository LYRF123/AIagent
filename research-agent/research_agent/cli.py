from __future__ import annotations

import argparse
import json

from .agent import ResearchAssistant
from .evaluation import run_evaluation


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

    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--ids", nargs="*")
    compare_parser.add_argument("--query")
    compare_parser.add_argument("--focus", default="methods, findings, and limitations")

    review_parser = subparsers.add_parser("review")
    review_parser.add_argument("--topic", required=True)
    review_parser.add_argument("--top-k", type=int, default=5)

    eval_parser = subparsers.add_parser("eval")
    eval_parser.add_argument("--eval-path", default=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    agent = ResearchAssistant(corpus_path=args.corpus)

    if args.command == "search":
        payload = agent.search_papers(args.query, top_k=args.top_k)
    elif args.command == "ask":
        payload = agent.answer_question(args.question, top_k=args.top_k).model_dump()
    elif args.command == "compare":
        payload = agent.compare_papers(paper_ids=args.ids, query=args.query, focus=args.focus).model_dump()
    elif args.command == "review":
        payload = agent.generate_review(args.topic, top_k=args.top_k).model_dump()
    else:
        payload = run_evaluation(agent, eval_path=args.eval_path)

    print(json.dumps(payload, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
