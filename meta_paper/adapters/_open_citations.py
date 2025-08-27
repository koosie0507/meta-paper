import re
from typing import Iterable, Literal

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    wait_exponential_jitter,
    stop_after_delay,
)

from meta_paper.adapters._base import PaperDetails, PaperListing, PaperMetadataAdapter
from meta_paper.adapters._doi_prefix import DOIPrefixMixin
from meta_paper.search import QueryParameters


def _retry_open_citations(exc: BaseException) -> bool:
    if isinstance(exc, httpx.ReadTimeout):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
        return True
    return False


class OpenCitationsAdapter(DOIPrefixMixin, PaperMetadataAdapter):
    REFERENCES_REST_API = "https://opencitations.net/index/api/v2"
    META_REST_API = "https://w3id.org/oc/meta/api/v1"
    DOI_RE = re.compile(r"^(doi:10\.\d{4,9}/\S+)$", re.IGNORECASE)

    def __init__(
        self, http_client: httpx.AsyncClient, api_token: str | None = None
    ) -> None:
        self.__http = http_client
        self.__headers = {} if not api_token else {"Authorization": api_token}

    @property
    def http_headers(self):
        return self.__headers

    async def search(self, _: QueryParameters) -> list[PaperListing]:
        return []

    async def __get_related(
        self, doi: str, relation_type: Literal["references", "citations"]
    ):
        endpoint_url = f"{self.REFERENCES_REST_API}/{relation_type}/{doi}"
        response = await self.__http.get(endpoint_url, headers=self.__headers)
        response.raise_for_status()

        citation_attr = "cited" if relation_type == "references" else "citing"
        return [
            self.DOI_RE.search(ref[citation_attr]).group(1)
            for ref in response.json()
            if self.DOI_RE.search(ref[citation_attr])
        ]

    @retry(
        retry=retry_if_exception(_retry_open_citations),
        wait=wait_exponential_jitter(max=10),
        stop=stop_after_delay(10),
    )
    async def get_one(self, doi: str | Iterable[str]) -> PaperDetails:
        """Fetch references and citations for a DOI."""
        doi = self._prepend_doi(doi, False)
        if not self.DOI_RE.match(doi):
            raise ValueError(f"{doi} is not a valid DOI")

        refs = await self.__get_related(doi, "references")
        citations = await self.__get_related(doi, "citations")

        response = await self.__http.get(
            f"{self.META_REST_API}/metadata/{doi}", headers=self.__headers
        )
        response.raise_for_status()
        metadata = next(iter(response.json()))

        return PaperDetails(
            doi=doi,
            title=metadata["title"],
            authors=metadata.get("authors", "").split(";"),
            abstract="",
            references=refs,
            citations=citations,
            source=metadata.get("venue", ""),
            url=f"https://dx.doi.org/{doi}",
        )

    async def get_many(self, identifiers: Iterable[str]) -> Iterable[PaperDetails]:
        return []
