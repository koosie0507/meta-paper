from http import HTTPStatus
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import Response

from meta_paper.adapters import OpenCitationsAdapter


@pytest.fixture
def oc_refs_response():
    return Response(200, json=[{"cited": "doi:10.1234/5678"}])


@pytest.fixture
def oc_metadata_response():
    return Response(200, json=[{"title": "abc def", "authors": "name surname"}])


@pytest.fixture
def request_handler_side_effect(oc_refs_response, oc_metadata_response):
    def __handler(request):
        req_url = str(request.url)
        responses = {
            "https://opencitations.net/index/api/v2/references/doi:10.1234/5678": oc_refs_response,
            "https://w3id.org/oc/meta/api/v1/metadata/doi:10.1234/5678": oc_metadata_response,
        }
        return responses[req_url]

    return __handler


@pytest.fixture
def request_handler(request_handler_side_effect):
    return AsyncMock(
        name="default_request_handler", side_effect=request_handler_side_effect
    )


@pytest.fixture
def sut(http_client, auth_token):
    return OpenCitationsAdapter(http_client, auth_token)


def test_init_defaults(sut):
    assert sut.http_headers == {}


@pytest.mark.parametrize(
    "auth_token,expected",
    [("abc", {"Authorization": "abc"}), (None, {}), ("", {})],
    indirect=["auth_token"],
)
def test_init_api_token(sut, auth_token, expected):
    assert sut.http_headers == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "doi,auth_token,expected_auth",
    [
        ("doi:10.1234/5678", None, None),
        ("10.1234/5678", None, None),
        ("10.1234/5678", "abcd", "abcd"),
    ],
)
async def test_details_makes_expected_call_to_references_api(
    sut, request_handler, doi, auth_token, expected_auth
):
    await sut.details(doi)

    assert len(request_handler.call_args_list) == 2
    refs_request = request_handler.call_args_list[0].args[0]
    assert refs_request.method == "GET"
    assert refs_request.url.path == "/index/api/v2/references/doi:10.1234/5678"
    assert refs_request.headers.get("Authorization") == expected_auth

    meta_request = request_handler.call_args_list[1].args[0]
    assert (
        str(meta_request.url)
        == "https://w3id.org/oc/meta/api/v1/metadata/doi:10.1234/5678"
    )
    assert meta_request.method == "GET"
    assert meta_request.headers.get("Authorization") == expected_auth


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code", [status for status in HTTPStatus if status >= 400 and status != 429]
)
async def test_details_raise_error_on_refs_error_re(
    sut, request_handler, oc_refs_response, status_code
):
    oc_refs_response.status_code = status_code

    with pytest.raises(httpx.HTTPStatusError) as err_wrapper:
        await sut.details("10.1234/5678")

    assert err_wrapper.value is not None
    assert str(status_code) in str(err_wrapper.value)
    assert len(request_handler.call_args_list) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code", [status for status in HTTPStatus if status >= 400 and status != 429]
)
async def test_details_raise_error_on_metadata_endpoint_error(
    sut, request_handler, oc_metadata_response, status_code
):
    oc_metadata_response.status_code = status_code

    with pytest.raises(httpx.HTTPStatusError) as err_wrapper:
        await sut.details("10.1234/5678")

    assert err_wrapper.value is not None
    assert str(status_code) in str(err_wrapper.value)
    assert len(request_handler.call_args_list) == 2


@pytest.mark.asyncio
async def test_search_returns_empty_search_results_list(sut, query_parameters):
    results = await sut.search(query_parameters)
    assert len(results) == 0
