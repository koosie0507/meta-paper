from dataclasses import dataclass
from typing import Protocol, Iterable

from meta_paper.search import QueryParameters


@dataclass
class PaperListing:
    doi: str
    title: str
    authors: list[str]

    def __hash__(self):
        return hash(self.doi)


@dataclass
class PaperDetails:
    doi: str
    title: str
    authors: list[str]
    abstract: str
    source: str
    citations: list[str]
    references: list[str]
    url: str
    has_pdf: bool = False
    pdf_url: str | None = None

    def __hash__(self):
        return hash(self.doi)


class PaperMetadataAdapter(Protocol):
    async def search(self, query: QueryParameters) -> list[PaperListing]:
        pass

    async def get_one(self, doi: str) -> PaperDetails:
        pass

    async def get_many(self, identifiers: Iterable[str]) -> Iterable[PaperDetails]:
        pass
