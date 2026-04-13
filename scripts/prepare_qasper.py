from __future__ import annotations

import argparse
import json
from pathlib import Path


def extract_eval_cases(record: dict) -> list[dict]:
    title = record.get("title", "")
    paper_id = record.get("paper_id") or title.lower().replace(" ", "_")
    cases = []
    for qa in record.get("qas", [])[:10]:
        question = qa.get("question", "").strip()
        if not question:
            continue
        cases.append(
            {
                "case_id": f"{paper_id}:{len(cases)}",
                "question": question,
                "expected_paper_ids": [paper_id],
                "expected_keywords": [],
            }
        )
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert QASPER JSON to the local eval format")
    parser.add_argument("--input", required=True, help="Path to a QASPER JSON file")
    parser.add_argument("--output", required=True, help="Path to the output eval JSON")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()

    with Path(args.input).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)

    output = []
    for record in raw.values():
        output.extend(extract_eval_cases(record))
        if len(output) >= args.limit:
            break

    output = output[: args.limit]
    with Path(args.output).open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
