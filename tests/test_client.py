import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from meta_paper.adapters import PaperMetadataAdapter, PaperListing, PaperDetails
from meta_paper.client import PaperMetadataClient
from meta_paper.search import QueryParameters


class StubProvider(PaperMetadataAdapter):
    def __init__(self, search_results=None, details=None):
        self._results = search_results or []
        self._details = details or PaperDetails(
            "doi:10.1234/5678",
            "test title",
            ["test author"],
            "test abstract",
            "test venue",
            ["10.1234/5678"],
            ["doi:10.1234/5678"],
            "https://example.org",
        )

    async def search(self, query: QueryParameters) -> list[PaperListing]:
        await asyncio.sleep(0.25)
        return self._results

    async def get_one(self, doi: str) -> PaperDetails:
        await asyncio.sleep(0.25)
        if isinstance(self._details, Exception):
            raise self._details
        return self._details


@pytest.fixture
def semantic_scholar_search_result():
    return {
        "title": "a title",
        "authors": [{"name": "author 1"}],
        "abstract": "an abstract",
        "externalIds": {"DOI": "123/456"},
    }


@pytest.fixture
def semantic_scholar_search_response(request, semantic_scholar_search_result):
    json_data = {"data": [semantic_scholar_search_result]}
    if hasattr(request, "param"):
        json_data = {"data": [request.param]}
    return httpx.Response(200, json=json_data)


@pytest.fixture
def request_handler(semantic_scholar_search_response):
    return AsyncMock(
        name="client_request_handler", return_value=semantic_scholar_search_response
    )


@pytest.fixture
def metadata_client(http_client, auth_token):
    return (
        PaperMetadataClient(http_client)
        .use_open_citations(auth_token)
        .use_semantic_scholar(auth_token)
    )


def test_client_init():
    sut = PaperMetadataClient()

    assert len(sut.providers) == 0


def test_use_open_citations_adds_expected_provider_type():
    sut = PaperMetadataClient().use_open_citations()

    assert len(sut.providers) == 1
    assert sut.providers[0].__class__.__name__ == "OpenCitationsAdapter"


def test_use_semantic_scholar_adds_expected_provider_type():
    sut = PaperMetadataClient().use_semantic_scholar()

    assert len(sut.providers) == 1
    assert sut.providers[0].__class__.__name__ == "SemanticScholarAdapter"


@pytest.mark.asyncio
async def test_search_calls_registered_providers(
    metadata_client, query_parameters, request_handler, default_title
):
    results = await metadata_client.search(query_parameters)

    assert len(request_handler.call_args_list) == 1
    req = request_handler.call_args_list[0].args[0]
    assert req.url.params["query"] == default_title
    assert req.url.path == "/graph/v1/paper/search"
    assert len(results) == 1


@pytest.mark.asyncio
async def test_get_one_returns_longest_doi(http_client):
    sut = (
        PaperMetadataClient(http_client)
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/5678",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/56789",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
    )
    actual = await sut.get_one("10.1234/5678")

    assert actual.doi == "10.1234/56789"


@pytest.mark.asyncio
async def test_get_one_returns_longest_title(http_client):
    sut = (
        PaperMetadataClient(http_client)
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/5678",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/56789",
                    "ti",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
    )
    actual = await sut.get_one("10.1234/5678")

    assert actual.title == "ti"


@pytest.mark.asyncio
async def test_get_one_returns_longest_abstract(http_client):
    sut = (
        PaperMetadataClient(http_client)
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/5678",
                    "t",
                    ["a"],
                    "a2",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/56789",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
    )
    actual = await sut.get_one("10.1234/5678")

    assert actual.abstract == "a2"


@pytest.mark.asyncio
async def test_get_one_returns_unique_authors(http_client):
    sut = (
        PaperMetadataClient(http_client)
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/5678",
                    "t",
                    ["a"],
                    "a2",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/56789",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
    )
    actual = await sut.get_one("10.1234/5678")

    assert actual.authors == ["a"]


@pytest.mark.asyncio
async def test_get_one_returns_unique_refs(http_client):
    sut = (
        PaperMetadataClient(http_client)
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/5678",
                    "t",
                    ["a"],
                    "a2",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/56789",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
    )
    actual = await sut.get_one("10.1234/5678")

    assert actual.references == ["10.1234/5678"]


@pytest.mark.asyncio
async def test_get_one_returns_data_from_successful_provider(http_client):
    sut = (
        PaperMetadataClient(http_client)
        .use_custom_provider(StubProvider(details=Exception("test error")))
        .use_custom_provider(
            StubProvider(
                details=PaperDetails(
                    "10.1234/56789",
                    "t",
                    ["a"],
                    "a",
                    "venue",
                    ["10.1234/5678"],
                    ["10.1234/5678"],
                    "https://example.org",
                )
            )
        )
    )
    actual = await sut.get_one("10.1234/5678")

    assert actual.doi == "10.1234/56789"
    assert actual.title == "t"
    assert actual.authors == ["a"]
    assert actual.abstract == "a"
    assert actual.references == ["10.1234/5678"]
