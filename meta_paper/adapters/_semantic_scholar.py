from datetime import timedelta
from typing import Iterable

import httpx
from tenacity import (
    retry,
    stop_after_delay,
    wait_exponential_jitter,
    retry_if_exception,
)

from meta_paper.adapters._base import PaperListing, PaperDetails, PaperMetadataAdapter
from meta_paper.adapters._doi_prefix import DOIPrefixMixin
from meta_paper.search import QueryParameters


def _retry_semantic_scholar(exc: BaseException) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429


class SemanticScholarAdapter(DOIPrefixMixin, PaperMetadataAdapter):
    __BASE_URL = "https://api.semanticscholar.org/graph/v1"
    __DETAIL_FIELDS = {
        "fields": "externalIds,title,authors,references.externalIds,abstract,isOpenAccess,openAccessPdf"
    }

    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None):
        self.__http = http_client
        self.__request_headers = {} if not api_key else {"x-api-key": api_key}

    @property
    def request_headers(self) -> dict:
        return self.__request_headers

    @retry(
        retry=retry_if_exception(_retry_semantic_scholar),
        stop=stop_after_delay(timedelta(seconds=10)),
        wait=wait_exponential_jitter(1, 8),
    )
    async def search(self, query: QueryParameters) -> list[PaperListing]:
        search_endpoint = f"{self.__BASE_URL}/paper/search"
        query_params = query.semantic_scholar().set(
            "fields", "title,externalIds,authors"
        )
        response = await self.__http.get(
            search_endpoint, headers=self.__request_headers, params=query_params
        )
        response.raise_for_status()

        search_results = response.json().get("data", [])
        result = []
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

    @retry(
        retry=retry_if_exception(_retry_semantic_scholar),
        stop=stop_after_delay(timedelta(seconds=10)),
        wait=wait_exponential_jitter(1, 8),
    )
    async def get_one(self, doi: str) -> PaperDetails:
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

        return PaperDetails(
            doi=self.__get_doi(paper_data.get("externalIds")),
            title=title,
            authors=authors,
            abstract=abstract,
            references=self.__get_references(paper_data),
            has_pdf=paper_data.get("isOpenAccess") or False,
            pdf_url=self.__get_pdf_url(paper_data),
        )

    @retry(
        retry=retry_if_exception(_retry_semantic_scholar),
        stop=stop_after_delay(timedelta(seconds=60)),
        wait=wait_exponential_jitter(1, 8),
    )
    async def get_many(self, identifiers: Iterable[str]) -> Iterable[PaperDetails]:
        if identifiers:
            identifiers = list(map(self._prepend_doi, filter(bool, identifiers)))
        if not identifiers:
            return []

        response = await self.__http.post(
            f"{self.__BASE_URL}/paper/batch",
            headers=self.__request_headers,
            params=self.__DETAIL_FIELDS,
            json={"ids": identifiers},
        )
        response.raise_for_status()

        paper_list = response.json()
        result = []
        for paper_data in paper_list:
            if not (title := paper_data.get("title")):
                print("paper title missing")
                continue
            if not (authors := self.__get_author_names(paper_data)):
                print("paper authors missing")
                continue
            if not (abstract := paper_data.get("abstract")):
                abstract = ""
            doi = self.__get_doi(paper_data.get("externalIds"))

            result.append(
                PaperDetails(
                    doi=doi,
                    title=title,
                    authors=authors,
                    abstract=abstract,
                    references=self.__get_references(paper_data),
                    has_pdf=paper_data.get("isOpenAccess") or False,
                    pdf_url=self.__get_pdf_url(paper_data),
                )
            )
        return result

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

    def __get_references(self, paper_data: dict) -> list[str]:
        if paper_data is None:
            return []
        ref_objs = list(filter(bool, paper_data.get("references") or []))
        external_id_objs = list(
            filter(bool, map(lambda x: x.get("externalIds"), ref_objs))
        )
        return list(filter(bool, map(self.__get_doi, external_id_objs)))
