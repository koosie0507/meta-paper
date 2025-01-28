from dataclasses import dataclass
from typing import Protocol

from meta_paper.search import QueryParameters


@dataclass
class PaperListing:
    doi: str
    title: str
    authors: list[str]


@dataclass
class PaperDetails:
    doi: str
    title: str
    authors: list[str]
    abstract: str
    references: list[str]


class PaperMetadataAdapter(Protocol):
    async def search(self, query: QueryParameters) -> list[PaperListing]:
        pass

    async def details(self, doi: str) -> PaperDetails:
        pass
