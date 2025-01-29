import re

import httpx

from meta_paper.adapters._base import PaperDetails, PaperListing, PaperMetadataAdapter
from meta_paper.adapters._doi_prefix import DOIPrefixMixin
from meta_paper.search import QueryParameters


class OpenCitationsAdapter(DOIPrefixMixin, PaperMetadataAdapter):
    REFERENCES_REST_API = "https://opencitations.net/index/api/v2"
    META_REST_API = "https://w3id.org/oc/meta/api/v1"
    DOI_RE = re.compile(r"\b(doi:[0-9a-z./]+)\b", re.IGNORECASE)

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

    async def details(self, doi: str) -> PaperDetails:
        """Fetch references and citations for a DOI."""
        doi = self._prepend_doi(doi, False)

        response = await self.__http.get(
            f"{self.REFERENCES_REST_API}/references/{doi}", headers=self.__headers
        )
        response.raise_for_status()

        refs = [
            self.DOI_RE.search(ref["cited"]).group(1)
            for ref in response.json()
            if self.DOI_RE.search(ref["cited"])
        ]

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
        )
