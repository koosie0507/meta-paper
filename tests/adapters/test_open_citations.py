from http import HTTPStatus
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import Response

from meta_paper.adapters import OpenCitationsAdapter
from meta_paper.search import QueryParameters


@pytest.fixture
def oc_refs_response():
    return Response(200, json=[{"cited": "doi:abc/def"}])


@pytest.fixture
def oc_metadata_response():
    return Response(200, json=[{"title": "abc def", "authors": "name surname"}])


@pytest.fixture
def default_request_handler(oc_refs_response, oc_metadata_response):
    def __handler(request):
        req_url = str(request.url)
        responses = {
            "https://opencitations.net/index/api/v2/references/doi:123/456": oc_refs_response,
            "https://w3id.org/oc/meta/api/v1/metadata/doi:123/456": oc_metadata_response,
        }
        return responses[req_url]

    return AsyncMock(name="default_request_handler", side_effect=__handler)


@pytest.fixture
def http_client(request, default_request_handler):
    handler = request.param if hasattr(request, "param") else default_request_handler
    return httpx.AsyncClient(transport=httpx.MockTransport(handler=handler))


@pytest.fixture
def api_token(request):
    return request.param if hasattr(request, "param") else None


@pytest.fixture
def query_parameters():
    class QueryParametersStub(QueryParameters[str]):
        def make(self) -> str:
            return ""
    return QueryParametersStub()

@pytest.fixture
def sut(http_client, api_token):
    return OpenCitationsAdapter(http_client, api_token)


def test_init_defaults(sut):
    assert sut.http_headers == {}


@pytest.mark.parametrize(
    "api_token,expected",
    [("abc", {"Authorization": "abc"}), (None, {}), ("", {})],
    indirect=["api_token"],
)
def test_init_api_token(sut, api_token, expected):
    assert sut.http_headers == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "doi,api_token,expected_auth",
    [("doi:123/456", None, None), ("123/456", None, None), ("123/456", "abcd", "abcd")],
)
async def test_details_makes_expected_call_to_references_api(
    sut, default_request_handler, doi, api_token, expected_auth
):
    await sut.details(doi)

    assert len(default_request_handler.call_args_list) == 2
    refs_request = default_request_handler.call_args_list[0].args[0]
    assert refs_request.method == "GET"
    assert (
        str(refs_request.url)
        == "https://opencitations.net/index/api/v2/references/doi:123/456"
    )
    assert refs_request.headers.get("Authorization") == expected_auth

    meta_request = default_request_handler.call_args_list[1].args[0]
    assert (
        str(meta_request.url) == "https://w3id.org/oc/meta/api/v1/metadata/doi:123/456"
    )
    assert meta_request.method == "GET"
    assert meta_request.headers.get("Authorization") == expected_auth


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [status for status in HTTPStatus if status >= 400])
async def test_details_raise_error_on_refs_error_re(sut, default_request_handler, oc_refs_response, status_code):
    oc_refs_response.status_code = status_code

    with pytest.raises(httpx.HTTPStatusError) as err_wrapper:
        await sut.details("123/456")

    assert err_wrapper.value is not None
    assert str(status_code) in str(err_wrapper.value)
    assert len(default_request_handler.call_args_list) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [status for status in HTTPStatus if status >= 400])
async def test_details_raise_error_on_metadata_endpoint_error(sut, default_request_handler, oc_metadata_response, status_code):
    oc_metadata_response.status_code = status_code

    with pytest.raises(httpx.HTTPStatusError) as err_wrapper:
        await sut.details("123/456")

    assert err_wrapper.value is not None
    assert str(status_code) in str(err_wrapper.value)
    assert len(default_request_handler.call_args_list) == 2


@pytest.mark.asyncio
async def test_search_returns_empty_search_results_list(sut, query_parameters):
    results = await sut.search(query_parameters)
    assert len(results) == 0
