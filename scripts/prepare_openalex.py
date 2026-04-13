from __future__ import annotations

import argparse
import json
from pathlib import Path


def decode_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    pairs = []
    for token, positions in index.items():
        for position in positions:
            pairs.append((position, token))
    return " ".join(token for _, token in sorted(pairs))


def convert_record(record: dict) -> dict:
    abstract = decode_abstract(record.get("abstract_inverted_index"))
    title = record.get("title") or ""
    concepts = [item.get("display_name", "") for item in record.get("concepts", [])[:8]]
    return {
        "paper_id": record["id"].rsplit("/", 1)[-1].lower(),
        "title": title,
        "year": int(record.get("publication_year") or 0),
        "venue": (record.get("primary_location") or {}).get("source", {}).get("display_name", ""),
        "authors": [
            author.get("author", {}).get("display_name", "")
            for author in record.get("authorships", [])[:8]
        ],
        "source_url": record.get("id", ""),
        "topics": [concept for concept in concepts if concept],
        "summary": abstract[:1200],
        "methods": [],
        "findings": [],
        "limitations": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert OpenAlex JSONL to the local corpus format")
    parser.add_argument("--input", required=True, help="Path to OpenAlex JSONL")
    parser.add_argument("--output", required=True, help="Output papers JSON path")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args()

    output = []
    input_path = Path(args.input)
    with input_path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            if index >= args.limit:
                break
            record = json.loads(line)
            output.append(convert_record(record))

    with Path(args.output).open("w", encoding="utf-8") as handle:
        json.dump(output, handle, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
