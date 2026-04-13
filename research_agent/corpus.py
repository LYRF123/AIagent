from __future__ import annotations

import json
from pathlib import Path

from .models import Paper, Passage


def default_data_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "demo_papers.json"


def default_imported_data_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "imported_papers.json"


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
    def from_json(cls, path: str | Path | None = None, imported_path: str | Path | None = None) -> "PaperCorpus":
        data_path = Path(path) if path else default_data_path()
        with data_path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        papers = [Paper.model_validate(item) for item in raw]

        imported_target = Path(imported_path) if imported_path else default_imported_data_path()
        imported_items: list[Paper] = []
        if imported_target.exists():
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
        return [self.paper_by_id[paper_id] for paper_id in paper_ids if paper_id in self.paper_by_id]

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
            passages.append(
                Passage(
                    passage_id=f"{paper.paper_id}:summary",
                    paper_id=paper.paper_id,
                    title=paper.title,
                    section="summary",
                    text=paper.summary,
                )
            )
            for section_name, values in (
                ("methods", paper.methods),
                ("findings", paper.findings),
                ("limitations", paper.limitations),
                ("topics", paper.topics),
            ):
                for index, value in enumerate(values):
                    passages.append(
                        Passage(
                            passage_id=f"{paper.paper_id}:{section_name}:{index}",
                            paper_id=paper.paper_id,
                            title=paper.title,
                            section=section_name,
                            text=value,
                        )
                    )
        return passages
