from unittest.mock import AsyncMock

import httpx
import pytest

from meta_paper.client import PaperMetadataClient


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
    return AsyncMock(name="client_request_handler", return_value=semantic_scholar_search_response)


@pytest.fixture
def metadata_client(http_client, auth_token):
    return PaperMetadataClient(http_client).use_open_citations(auth_token).use_semantic_scholar(auth_token)


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