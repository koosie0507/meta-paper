import httpx

from meta_paper.adapters._base import PaperListing, PaperDetails, PaperMetadataAdapter
from meta_paper.adapters._doi_prefix import DOIPrefixMixin
from meta_paper.search import QueryParameters


class SemanticScholarAdapter(DOIPrefixMixin, PaperMetadataAdapter):
    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, http_client: httpx.AsyncClient, api_key: str | None = None):
        self.__http = http_client
        self.__request_headers = {} if not api_key else {"x-api-key": api_key}

    @property
    def request_headers(self) -> dict:
        return self.__request_headers

    async def search(self, query: QueryParameters) -> list[PaperListing]:
        search_endpoint = f"{self.BASE_URL}/paper/search"
        query_params = query.semantic_scholar().set(
            "fields", "title,externalIds,authors"
        )
        response = await self.__http.get(
            search_endpoint, headers=self.__request_headers, params=query_params
        )
        response.raise_for_status()

        search_results = response.json().get("data", [])
        return [
            PaperListing(
                doi=paper_info["externalIds"]["DOI"],
                title=paper_info["title"],
                authors=author_names,
            )
            for paper_info in search_results
            if self.__has_valid_doi(paper_info)
            and paper_info.get("title")
            and (author_names := self.__get_author_names(paper_info))
        ]

    async def details(self, doi: str) -> PaperDetails:
        doi = self._prepend_doi(doi)
        paper_details_endpoint = f"{self.BASE_URL}/paper/{doi}"
        params = {"fields": "title,authors,references.externalIds,abstract"}
        response = await self.__http.get(
            paper_details_endpoint, headers=self.__request_headers, params=params
        )
        response.raise_for_status()

        paper_data = response.json()
        if not (title := paper_data.get("title")):
            raise ValueError("paper title missing")
        if not (authors := self.__get_author_names(paper_data)):
            raise ValueError("paper authors missing")
        if not (abstract := paper_data.get("abstract")):
            raise ValueError("paper abstract missing")

        return PaperDetails(
            doi=doi,
            title=title,
            authors=authors,
            abstract=abstract,
            references=[
                self._prepend_doi(ref["externalIds"]["DOI"])
                for ref in paper_data["references"]
                if self.__has_valid_doi(ref)
            ],
        )

    @staticmethod
    def __has_valid_doi(paper_info: dict) -> bool:
        if not paper_info.get("externalIds"):
            return False
        if "DOI" not in paper_info["externalIds"]:
            return False
        return bool(paper_info["externalIds"]["DOI"])

    @staticmethod
    def __get_author_names(author_data: dict) -> list[str]:
        if not author_data.get("authors"):
            return []
        if not any("name" in x and x["name"] for x in author_data["authors"]):
            return []

        return list(map(str, (author["name"] for author in author_data["authors"])))
