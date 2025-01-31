import asyncio
import itertools
from collections.abc import Sequence
from typing import Iterable, Generator

import httpx
from tenacity import RetryError

from meta_paper.adapters import (
    OpenCitationsAdapter,
    SemanticScholarAdapter,
    PaperListing,
    PaperDetails,
    PaperMetadataAdapter,
)
from meta_paper.search import QueryParameters


class PaperMetadataClient:
    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self.__providers: list[PaperMetadataAdapter] = []
        self.__http = http_client or httpx.AsyncClient(
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "deflate,gzip;q=1.0",
            }
        )

    @property
    def providers(self) -> Sequence[PaperMetadataAdapter]:
        return self.__providers

    def use_open_citations(self, token: str | None = None) -> "PaperMetadataClient":
        """Add OpenCitations adapter to the client."""
        self.__providers.append(OpenCitationsAdapter(self.__http, token))
        return self

    def use_semantic_scholar(self, api_key: str | None = None):
        """Add SemanticScholar adapter to the client."""
        self.__providers.append(SemanticScholarAdapter(self.__http, api_key))
        return self

    def use_custom_provider(
        self, provider: PaperMetadataAdapter
    ) -> "PaperMetadataClient":
        self.__providers.append(provider)
        return self

    async def search(self, query: QueryParameters) -> list[PaperListing]:
        """Perform an asynchronous search across all providers."""
        tasks = [provider.search(query) for provider in self.providers]
        results = await asyncio.gather(*tasks)
        results = list(itertools.chain.from_iterable(results))
        return list(self.__dedupe_by_doi(results))

    async def details(self, doi: str) -> PaperDetails:
        """Fetch paper summaries asynchronously from all providers."""
        tasks = [provider.details(doi) for provider in self.providers]
        summaries = []
        for coro in asyncio.as_completed(tasks):
            try:
                summaries.append(await coro)
            except RetryError:
                print(f"retry count exceeded for doi '{doi}'")
            except Exception as exc:
                print("generic error fetching '%s': %s" % (doi, exc))

        doi = max((summary.doi for summary in summaries), key=len, default="")
        title = max((summary.title for summary in summaries), key=len, default="")
        abstract = max((summary.abstract for summary in summaries), key=len, default="")
        refs = set(
            itertools.chain.from_iterable(summary.references for summary in summaries)
        )
        authors = set(
            author
            for author in itertools.chain.from_iterable(
                summary.authors for summary in summaries
            )
            if author
        )
        return PaperDetails(
            doi=doi,
            title=title,
            abstract=abstract,
            references=list(refs),
            authors=list(authors),
        )

    @staticmethod
    def __dedupe_by_doi(
        results: Iterable[PaperListing],
    ) -> Generator[PaperListing, None, None]:
        """Remove duplicates based on DOI or title."""
        seen = set()
        for result in results:
            if result.doi in seen:
                continue
            seen.add(result.doi)
            yield result
