import itertools
from datetime import timedelta
from collections.abc import Iterable
from http import HTTPStatus
from logging import Logger
from typing import Literal

import httpx
from tenacity import (
    stop_after_delay,
    wait_exponential_jitter,
    retry_if_exception,
    AsyncRetrying,
)

from meta_paper.adapters._base import PaperListing, PaperDetails, PaperMetadataAdapter
from meta_paper.adapters._doi_prefix import DOIPrefixMixin
from meta_paper.logging import null_logger
from meta_paper.search import QueryParameters


class SemanticScholarAdapter(DOIPrefixMixin, PaperMetadataAdapter):
    __BASE_URL = "https://api.semanticscholar.org/graph/v1"
    __DETAIL_FIELDS = {
        "fields": "externalIds,title,authors,publicationVenue,referenceCount,citationCount,citations.externalIds,references.externalIds,abstract,isOpenAccess,openAccessPdf,url,year"
    }
    __RETRY_MESSAGES = {
        int(HTTPStatus.TOO_MANY_REQUESTS): "rate limited",
        int(HTTPStatus.GATEWAY_TIMEOUT): "gateway timeout",
    }
    __BATCH_SIZE = 500
    __MAX_RELATED = (
        9999  # undocumented limitation of the citations and references endpoints
    )

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        api_key: str | None = None,
        logger: Logger | None = None,
    ) -> None:
        self.__http = http_client
        self.__request_headers = {} if not api_key else {"x-api-key": api_key}
        self.__logger = logger or null_logger()

    def _retry_semantic_scholar(self, exc: BaseException) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            err_message = self.__RETRY_MESSAGES.get(exc.response.status_code)
            if err_message:
                self.__logger.warning("retrying: %s", err_message)
                return True
        return False

    @property
    def request_headers(self) -> dict:
        return self.__request_headers

    async def search(self, query: QueryParameters) -> list[PaperListing]:
        result = []
        async for attempt in self.__new_retry_manager():
            with attempt:
                search_endpoint = f"{self.__BASE_URL}/paper/search"
                query_params = query.semantic_scholar().set(
                    "fields", "title,externalIds,authors"
                )
                response = await self.__http.get(
                    search_endpoint, headers=self.__request_headers, params=query_params
                )
                response.raise_for_status()

                search_results = response.json().get("data", [])
                for paper_info in search_results:
                    if not self.__has_valid_doi(paper_info):
                        continue
                    if not paper_info.get("title"):
                        continue
                    if not (author_names := self.__get_author_names(paper_info)):
                        continue
                    result.append(
                        PaperListing(
                            doi=paper_info["externalIds"]["DOI"],
                            title=paper_info["title"],
                            authors=author_names,
                        )
                    )
        return result

    async def get_one(self, doi: str) -> PaperDetails:
        async for attempt in self.__new_retry_manager():
            with attempt:
                doi = self._prepend_doi(doi)
                paper_details_endpoint = f"{self.__BASE_URL}/paper/{doi}"
                response = await self.__http.get(
                    paper_details_endpoint,
                    headers=self.__request_headers,
                    params=self.__DETAIL_FIELDS,
                )
                response.raise_for_status()

                paper_data = response.json()
                if not (title := paper_data.get("title")):
                    raise ValueError("paper title missing")
                if not (authors := self.__get_author_names(paper_data)):
                    raise ValueError("paper authors missing")
                if not (abstract := paper_data.get("abstract")):
                    abstract = ""
                if not (source := self.__get_publication_venue(paper_data)):
                    source = ""
                if not (url := paper_data.get("url")):
                    url = ""

        return PaperDetails(
            doi=self.__get_doi(paper_data.get("externalIds")),
            title=title,
            authors=authors,
            abstract=abstract,
            citation_count=paper_data.get("citationCount", 0),
            citations=await self.__get_related_papers(paper_data, "citations"),
            reference_count=paper_data.get("referenceCount", 0),
            references=await self.__get_related_papers(paper_data),
            has_pdf=paper_data.get("isOpenAccess") or False,
            pdf_url=self.__get_pdf_url(paper_data),
            url=url,
            source=source,
            year=self.__get_year(paper_data),
        )

    async def get_many(self, identifiers: Iterable[str]) -> Iterable[PaperDetails]:
        if identifiers:
            identifiers = list(map(self._prepend_doi, filter(bool, identifiers)))
        if not identifiers:
            return []

        result = []
        for batch in self.__batch(identifiers):
            result.extend(await self.__process_identifier_batch(batch))
        return result

    async def __process_identifier_batch(self, batch: list[str]) -> list[PaperDetails]:
        result = []
        async for attempt in self.__new_retry_manager():
            with attempt:
                response = await self.__http.post(
                    f"{self.__BASE_URL}/paper/batch",
                    headers=self.__request_headers,
                    params=self.__DETAIL_FIELDS,
                    json={"ids": batch},
                )
                response.raise_for_status()
                paper_list = response.json()

                for paper_data in paper_list:
                    if paper_data is None:
                        continue
                    if not (title := paper_data.get("title")):
                        self.__logger.debug("paper title missing")
                        continue
                    if not (authors := self.__get_author_names(paper_data)):
                        self.__logger.debug("paper authors missing")
                        continue
                    if not (abstract := paper_data.get("abstract")):
                        abstract = ""
                    if not (source := self.__get_publication_venue(paper_data)):
                        source = ""
                    if not (url := paper_data.get("url")):
                        url = ""
                    doi = self.__get_doi(paper_data.get("externalIds"))

                    result.append(
                        PaperDetails(
                            doi=doi,
                            title=title,
                            authors=authors,
                            abstract=abstract,
                            citation_count=paper_data.get("citationCount", 0),
                            citations=await self.__get_related_papers(
                                paper_data, "citations"
                            ),
                            reference_count=paper_data.get("referenceCount", 0),
                            references=await self.__get_related_papers(paper_data),
                            has_pdf=paper_data.get("isOpenAccess") or False,
                            pdf_url=self.__get_pdf_url(paper_data),
                            source=source,
                            url=url,
                            year=self.__get_year(paper_data),
                        )
                    )
        return result

    def __new_retry_manager(self) -> AsyncRetrying:
        return AsyncRetrying(
            retry=retry_if_exception(self._retry_semantic_scholar),
            stop=stop_after_delay(timedelta(seconds=60)),
            wait=wait_exponential_jitter(3, 27, 3, 1.5),
        )

    @staticmethod
    def __get_year(paper_data: dict) -> int:
        if "year" not in paper_data:
            return -1
        year_str = str(paper_data["year"] or -1)
        return int(year_str)

    @staticmethod
    def __has_valid_doi(paper_info: dict) -> bool:
        if not paper_info.get("externalIds"):
            return False
        if "DOI" not in paper_info["externalIds"]:
            return False
        return bool(paper_info["externalIds"]["DOI"])

    @staticmethod
    def __get_author_names(author_data: dict) -> list[str]:
        if author_data is None:
            return []
        author_objs = list(filter(bool, author_data.get("authors") or []))
        authors = list(filter(bool, map(lambda x: x.get("name"), author_objs)))
        return list(map(str, authors))

    @staticmethod
    def __get_publication_venue(paper_data: dict) -> str:
        if paper_data is None:
            return ""
        venue_info = paper_data.get("publicationVenue") or {}
        return venue_info.get("name") or ""

    @staticmethod
    def __get_pdf_url(paper_data: dict) -> str:
        if paper_data is None:
            return ""
        pdf_info = paper_data.get("openAccessPdf") or {}
        return pdf_info.get("url") or ""

    def __get_doi(self, external_ids_obj: dict) -> str:
        if external_ids_obj is None:
            return ""
        doi = external_ids_obj.get("DOI") or ""
        if not doi:
            return ""
        return self._prepend_doi(doi)

    @staticmethod
    def __get_related_paper_count(
        paper_data: dict, relation_type: Literal["citations", "references"]
    ) -> int:
        match relation_type:
            case "citations":
                return paper_data.get("citationCount", 0)
            case "references":
                return paper_data.get("referenceCount", 0)

    async def __fetch_related_papers(
        self,
        paper_data: dict,
        related_paper_count: int,
        relation_type: Literal["citations", "references"] = "references",
    ):
        paper_data_doi = paper_data.get("externalIds", {}).get("DOI")
        canonical_doi = self._prepend_doi(paper_data_doi)
        related_url = f"{self.__BASE_URL}/paper/{canonical_doi}/{relation_type}"
        related_paper_field = (
            "citedPaper" if relation_type == "references" else "citingPaper"
        )
        related_papers = []
        try:
            for offset in range(0, related_paper_count, self.__BATCH_SIZE):
                limit = min(related_paper_count - offset, self.__BATCH_SIZE)
                self.__logger.info(
                    "fetching %s %s %d-%d",
                    paper_data_doi,
                    relation_type,
                    offset,
                    offset + limit,
                )
                page_params = dict(
                    offset=offset,
                    limit=limit,
                    fields=f"{related_paper_field}.externalIds",
                )
                async for attempt in self.__new_retry_manager():
                    with attempt:
                        response = await self.__http.get(
                            related_url,
                            headers=self.__request_headers,
                            params=page_params,
                        )
                        response.raise_for_status()
                        json = response.json()
                        related_papers.extend(
                            [
                                item.get(related_paper_field, {})
                                for item in json.get("data", [])
                            ]
                        )
                        self.__logger.info(json.get("next"))
        except httpx.HTTPError as e:
            msg = e.response.text if hasattr(e, "response") else str(e)
            self.__logger.warning(
                "fetch %s %s caught error: %s", paper_data_doi, relation_type, msg
            )
        self.__logger.info(
            "fetched %d %s for %s", len(related_papers), relation_type, paper_data_doi
        )
        return related_papers

    async def __get_related_papers(
        self,
        paper_data: dict,
        relation_type: Literal["citations", "references"] = "references",
    ) -> list[str]:
        if paper_data is None:
            return []
        # can't get more than __MAX_RELATED citations/references via ANY graph API endpoint
        count = min(
            self.__get_related_paper_count(paper_data, relation_type),
            self.__MAX_RELATED,
        )
        related = paper_data.get(relation_type) or []
        if count > len(related):
            # Semantic Scholar truncated the references/citations
            self.__logger.info(
                "initial fetch got %d out of %d %s. refetching",
                len(related),
                count,
                relation_type,
            )
            related_papers = await self.__fetch_related_papers(
                paper_data, count, relation_type
            )
            ref_objs = list(filter(bool, related_papers))
        else:
            ref_objs = list(filter(bool, related))

        external_id_objs = list(
            filter(bool, map(lambda x: x.get("externalIds"), ref_objs))
        )
        return list(filter(bool, map(self.__get_doi, external_id_objs)))

    @staticmethod
    def __batch(
        identifiers: Iterable[str], batch_size: int = __BATCH_SIZE
    ) -> Iterable[list[str]]:
        it = iter(identifiers)
        while True:
            batch = list(itertools.islice(it, batch_size))
            if not batch:
                return
            yield batch
