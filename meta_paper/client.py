import asyncio
import itertools
from collections.abc import Sequence
from logging import Logger
from typing import Iterable, Generator, Callable

import httpx
from tenacity import RetryError

from meta_paper.adapters import (
    OpenCitationsAdapter,
    SemanticScholarAdapter,
    PaperListing,
    PaperDetails,
    PaperMetadataAdapter,
)
from meta_paper.logging import null_logger
from meta_paper.search import QueryParameters


class PaperMetadataClient:
    def __init__(
        self, http_client: httpx.AsyncClient | None = None, logger: Logger | None = None
    ) -> None:
        self.__providers: list[PaperMetadataAdapter] = []
        self.__http = http_client or httpx.AsyncClient(
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "deflate,gzip;q=1.0",
            }
        )
        self.__logger = (logger or null_logger()).getChild(self.__class__.__name__)

    @property
    def providers(self) -> Sequence[PaperMetadataAdapter]:
        return self.__providers

    def use_open_citations(self, token: str | None = None) -> "PaperMetadataClient":
        """Add OpenCitations adapter to the client."""
        self.__providers.append(OpenCitationsAdapter(self.__http, token))
        return self

    def use_semantic_scholar(self, api_key: str | None = None):
        """Add SemanticScholar adapter to the client."""
        self.__providers.append(
            SemanticScholarAdapter(
                self.__http, api_key, self.__logger.getChild("SemanticScholarAdapter")
            )
        )
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

    async def get_one(self, doi: str) -> PaperDetails:
        """Fetch paper summaries asynchronously from all providers."""
        tasks = [provider.get_one(doi) for provider in self.providers]
        paper_data = []

        for coro in asyncio.as_completed(tasks):
            try:
                paper_data.append(await coro)
            except RetryError:
                self.__logger.error("retry count exceeded for doi '%s'", doi)
            except Exception as exc:
                self.__logger.fatal("generic error fetching '%s': %s", doi, exc)
                self.__logger.debug("error details", exc_info=exc)

        return self.__to_paper_details(paper_data)

    async def get_many(self, identifiers: Iterable[str]) -> Iterable[PaperDetails]:
        """Fetch paper summaries asynchronously from all providers."""
        tasks = [provider.get_many(identifiers) for provider in self.providers]
        paper_data = {}
        for coro in asyncio.as_completed(tasks):
            try:
                provider_papers = await coro
                for paper in provider_papers:
                    doi_papers = paper_data.get(paper.doi) or set()
                    doi_papers.add(paper)
                    paper_data[paper.doi] = doi_papers
            except RetryError as exc:
                self.__logger.error("retry count exceeded while fetching batch")
                self.__logger.debug("error details", exc_info=exc)
            except Exception as exc:
                self.__logger.fatal("generic error while fetching batch")
                self.__logger.debug("error details", exc_info=exc)

        return map(self.__to_paper_details, paper_data.values())

    def __to_paper_details(self, paper_data: Iterable[PaperDetails]) -> PaperDetails:
        doi = self.__longest_str(paper_data, lambda x: x.doi)
        title = self.__longest_str(paper_data, lambda x: x.title)
        abstract = self.__longest_str(paper_data, lambda x: x.abstract)
        unique_citations = list(
            sorted(set(itertools.chain.from_iterable(x.citations for x in paper_data)))
        )
        unique_references = list(
            sorted(set(itertools.chain.from_iterable(x.references for x in paper_data)))
        )
        unique_author_names = set(
            a for a in itertools.chain.from_iterable(d.authors for d in paper_data)
        )
        has_pdf = any(d.has_pdf for d in paper_data)
        pdf_url = self.__longest_str(paper_data, lambda x: x.pdf_url)
        url = self.__longest_str(paper_data, lambda x: x.url)
        source = self.__longest_str(paper_data, lambda x: x.source)
        return PaperDetails(
            doi=doi,
            title=title,
            abstract=abstract,
            source=source,
            citations=unique_citations,
            references=list(unique_references),
            authors=list(unique_author_names),
            has_pdf=has_pdf,
            pdf_url=pdf_url,
            url=url,
        )

    @staticmethod
    def __longest_str(
        items: Iterable[PaperDetails], attr_selector: Callable[[PaperDetails], str]
    ) -> str:
        generate_attr_values = (
            attr_value for obj in items if (attr_value := attr_selector(obj))
        )
        return max(generate_attr_values, key=len, default="")

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
