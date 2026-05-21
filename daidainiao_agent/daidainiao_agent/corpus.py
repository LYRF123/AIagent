from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Paper, Passage


SUMMARY_CHUNK_CHARS = 900
GENERIC_TOPIC_TERMS = {
    "article",
    "document",
    "file",
    "idea",
    "main",
    "method",
    "methods",
    "paper",
    "study",
    "upload",
    "uploaded",
}

# Regex for splitting text into sentences (handles .!? followed by space/capital).
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\u4e00-\u9fff])")


def default_data_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "demo_papers.json"


def default_imported_data_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "imported_papers.json"


def split_passage_text(
    value: str,
    chunk_size: int = SUMMARY_CHUNK_CHARS,
) -> list[str]:
    """Split text into chunks that respect sentence boundaries.

    Unlike the old fixed-window approach, this groups whole sentences
    together until the chunk would exceed *chunk_size*.  A single
    over-long sentence is left as-is rather than being cut mid-word.
    """
    compact = " ".join(value.split())
    if not compact:
        return []
    if len(compact) <= chunk_size:
        return [compact]

    sentences = _SENTENCE_SPLIT.split(compact)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for sentence in sentences:
        s = sentence.strip()
        if not s:
            continue
        # +1 for the joining space
        need = len(s) + (1 if current else 0)
        if current_len + need <= chunk_size:
            current.append(s)
            current_len += need
        else:
            if current:
                chunks.append(" ".join(current))
            # If a single sentence exceeds chunk_size, fall back to
            # length-based splitting for that sentence only.
            if len(s) > chunk_size:
                # Split at word boundaries near chunk_size.
                words = s.split()
                buf: list[str] = []
                buf_len = 0
                for w in words:
                    need = len(w) + (1 if buf else 0)
                    if buf_len + need <= chunk_size:
                        buf.append(w)
                        buf_len += need
                    else:
                        if buf:
                            chunks.append(" ".join(buf))
                        buf = [w]
                        buf_len = len(w)
                if buf:
                    chunks.append(" ".join(buf))
                current = []
                current_len = 0
            else:
                current = [s]
                current_len = len(s)

    if current:
        chunks.append(" ".join(current))

    return chunks


def is_informative_topic(value: str) -> bool:
    normalized = " ".join(value.lower().split())
    return bool(normalized) and normalized not in GENERIC_TOPIC_TERMS


class PaperCorpus:
    def __init__(
        self,
        papers: list[Paper],
        imported_papers: list[Paper] | None = None,
        imported_path: str | Path | None = None,
    ) -> None:
        self.imported_path = Path(imported_path) if imported_path else default_imported_data_path()
        self.base_papers = list(papers)
        self.imported_papers = list(imported_papers or [])
        self._refresh_state()

    @classmethod
    def from_json(
        cls,
        path: str | Path | None = None,
        imported_path: str | Path | None = None,
        include_imported: bool = True,
    ) -> "PaperCorpus":
        data_path = Path(path) if path else default_data_path()
        with data_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        papers = [Paper.model_validate(item) for item in raw]

        imported_target = Path(imported_path) if imported_path else default_imported_data_path()
        imported_items: list[Paper] = []
        if include_imported and imported_target.exists():
            with imported_target.open("r", encoding="utf-8-sig") as handle:
                imported_raw = json.load(handle)
            imported_items = [Paper.model_validate(item) for item in imported_raw]

        return cls(papers, imported_papers=imported_items, imported_path=imported_target)

    def _refresh_state(self) -> None:
        self.papers = [*self.base_papers, *self.imported_papers]
        self.paper_by_id = {paper.paper_id: paper for paper in self.papers}
        self.passages = self._build_passages(self.papers)

    def get_paper(self, paper_id: str) -> Paper:
        return self.paper_by_id[paper_id]

    def get_papers(self, paper_ids: list[str]) -> list[Paper]:
        return [self.paper_by_id[paper_id] for paper_id in paper_ids]

    def add_imported_paper(self, paper: Paper, persist: bool = True) -> None:
        self.imported_papers = [item for item in self.imported_papers if item.paper_id != paper.paper_id]
        self.imported_papers.append(paper)
        self._refresh_state()
        if persist:
            self.persist_imported_papers()

    def delete_imported_paper(self, paper_id: str, persist: bool = True) -> Paper | None:
        removed: Paper | None = None
        retained: list[Paper] = []
        for paper in self.imported_papers:
            if paper.paper_id == paper_id and removed is None:
                removed = paper
                continue
            retained.append(paper)
        self.imported_papers = retained
        self._refresh_state()
        if persist:
            self.persist_imported_papers()
        return removed

    def persist_imported_papers(self) -> None:
        self.imported_path.parent.mkdir(parents=True, exist_ok=True)
        with self.imported_path.open("w", encoding="utf-8") as handle:
            json.dump([paper.model_dump() for paper in self.imported_papers], handle, ensure_ascii=False, indent=2)

    def list_imported_papers(self) -> list[Paper]:
        return list(self.imported_papers)

    def _build_passages(self, papers: list[Paper]) -> list[Passage]:
        passages: list[Passage] = []
        for paper in papers:
            source_label = paper.source_label or paper.title
            if paper.source_passages:
                for source_index, source_segment in enumerate(paper.source_passages):
                    summary_chunks = split_passage_text(source_segment.text)
                    for chunk_index, chunk in enumerate(summary_chunks):
                        if len(summary_chunks) == 1:
                            passage_id = f"{paper.paper_id}:summary:{source_index}"
                        else:
                            passage_id = f"{paper.paper_id}:summary:{source_index}:{chunk_index}"
                        locator = source_segment.locator or (
                            f"page {source_segment.page}" if source_segment.page is not None else ""
                        )
                        if len(summary_chunks) > 1:
                            locator = f"{locator} chunk {chunk_index + 1}".strip()
                        passages.append(
                            Passage(
                                passage_id=passage_id,
                                paper_id=paper.paper_id,
                                title=paper.title,
                                section="summary",
                                text=chunk,
                                source_url=source_segment.source_url or paper.source_url,
                                source_label=source_segment.source_label or source_label,
                                page=source_segment.page,
                                locator=locator,
                            )
                        )
            else:
                summary_chunks = split_passage_text(paper.summary)
                for index, chunk in enumerate(summary_chunks):
                    passage_id = f"{paper.paper_id}:summary" if len(summary_chunks) == 1 else f"{paper.paper_id}:summary:{index}"
                    passages.append(
                        Passage(
                            passage_id=passage_id,
                            paper_id=paper.paper_id,
                            title=paper.title,
                            section="summary",
                            text=chunk,
                            source_url=paper.source_url,
                            source_label=source_label,
                            page=paper.page,
                            locator=paper.locator,
                        )
                    )
            for section_name, values in (
                ("methods", paper.methods),
                ("findings", paper.findings),
                ("limitations", paper.limitations),
                ("topics", paper.topics),
            ):
                for index, value in enumerate(values):
                    if section_name == "topics" and not is_informative_topic(value):
                        continue
                    passages.append(
                        Passage(
                            passage_id=f"{paper.paper_id}:{section_name}:{index}",
                            paper_id=paper.paper_id,
                            title=paper.title,
                            section=section_name,
                            text=value,
                            source_url=paper.source_url,
                            source_label=source_label,
                            page=paper.page,
                            locator=paper.locator,
                        )
                    )
        return passages
