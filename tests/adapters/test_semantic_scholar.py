from http import HTTPStatus
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import HTTPStatusError

from meta_paper.adapters._semantic_scholar import SemanticScholarAdapter
from meta_paper.search import QueryParameters


@pytest.fixture
def search_response(request):
    json_data = {"data": []}
    if hasattr(request, "param"):
        json_data = {"data": [request.param]}
    return httpx.Response(200, json=json_data)


@pytest.fixture
def valid_detail():
    return {
        "title": "a title",
        "authors": [{"name": "author 1"}],
        "abstract": "an abstract",
        "references": [{"externalIds": {"DOI": "123/456"}}],
    }


@pytest.fixture
def details_response(request, valid_detail):
    json_data = valid_detail
    if hasattr(request, "param"):
        json_data = request.param
    return httpx.Response(200, json=json_data)


@pytest.fixture
def request_handler(search_response, details_response):
    def _handler(req):
        return (
            search_response
            if req.url.path == "/graph/v1/paper/search"
            else details_response
        )

    return AsyncMock(name="default_request_handler", side_effect=_handler)


@pytest.fixture
def sut(http_client, auth_token):
    return SemanticScholarAdapter(http_client, auth_token)


@pytest.mark.parametrize(
    "auth_token,expected",
    [(None, {}), ("abc", {"x-api-key": "abc"}), ("", {})],
    indirect=["auth_token"],
)
def test_init_expected_request_headers(sut, expected):
    assert sut.request_headers == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_token,expected_api_key",
    [(None, None), ("abc", "abc")],
    indirect=["auth_token"],
)
async def test_search_calls_search_endpoint(sut, request_handler, expected_api_key):
    results = await sut.search(QueryParameters())

    assert len(results) == 0
    assert len(request_handler.call_args_list) == 1
    search_request = request_handler.call_args_list[0].args[0]
    assert (
        str(search_request.url)
        == "https://api.semanticscholar.org/graph/v1/paper/search?fields=title%2CexternalIds%2Cauthors"
    )
    assert search_request.method == "GET"
    api_key = search_request.headers.get("x-api-key")
    assert api_key == expected_api_key


@pytest.mark.asyncio
async def test_search_uses_expected_query_parameters(sut, request_handler):
    await sut.search(QueryParameters().title("abc"))

    search_request = request_handler.call_args_list[0].args[0]
    assert search_request.url.params.get("query") == "abc"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_code", [code for code in HTTPStatus if code >= 400 and code != 429]
)
async def test_search_raises_exception_on_endpoint_error_response(
    sut, search_response, status_code
):
    search_response.status_code = status_code

    with pytest.raises(HTTPStatusError) as exc_wrapper:
        await sut.search(QueryParameters())

    assert str(status_code) in str(exc_wrapper.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search_response",
    [
        {"title": "a title", "authors": [{"name": "author 1"}]},
        {"title": "a title", "authors": [{"name": "author 1"}], "externalIDs": {}},
        {"title": "a title", "authors": [{"name": "author 1"}], "externalIds": {}},
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "externalIDs": {"isbn": ""},
        },
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "externalIDs": {"doi": ""},
        },
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "externalIDs": {"DOI": ""},
        },
    ],
    indirect=["search_response"],
)
async def test_search_does_not_return_papers_without_doi(sut, search_response):
    results = await sut.search(QueryParameters())

    assert len(results) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search_response",
    [
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "externalIds": {"DOI": "123/456"},
        },
    ],
    indirect=["search_response"],
)
async def test_search_returns_expected_value(sut, search_response):
    results = await sut.search(QueryParameters())

    assert len(results) == 1
    assert results[0].doi == "123/456"
    assert results[0].title == "a title"
    assert results[0].authors == ["author 1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search_response",
    [
        {"authors": [{"name": "author 1"}], "externalIds": {"DOI": "123/456"}},
        {
            "title": None,
            "authors": [{"name": "author 1"}],
            "externalIds": {"DOI": "123/456"},
        },
        {
            "title": "",
            "authors": [{"name": "author 1"}],
            "externalIds": {"DOI": "123/456"},
        },
    ],
    indirect=["search_response"],
)
async def test_search_does_not_return_entries_without_title(sut, search_response):
    results = await sut.search(QueryParameters())

    assert len(results) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search_response",
    [
        {"title": "a title", "externalIds": {"DOI": "123/456"}},
        {"title": "a title", "authors": None, "externalIds": {"DOI": "123/456"}},
        {"title": "a title", "authors": [], "externalIds": {"DOI": "123/456"}},
        {
            "title": "a title",
            "authors": [{"name1": "abc"}],
            "externalIds": {"DOI": "123/456"},
        },
        {
            "title": "a title",
            "authors": [{"name": None}],
            "externalIds": {"DOI": "123/456"},
        },
    ],
    indirect=["search_response"],
)
async def test_search_does_not_return_entries_without_author_names(
    sut, search_response
):
    results = await sut.search(QueryParameters())

    assert len(results) == 0


@pytest.mark.asyncio
async def test_details_returns_expected_data(sut):
    result = await sut.details("123/456")

    assert result.doi == "DOI:123/456"
    assert result.title == "a title"
    assert result.authors == ["author 1"]
    assert result.references == ["DOI:123/456"]
    assert result.abstract == "an abstract"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details_response",
    [
        {
            "authors": [{"name": "author 1"}],
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": None,
            "authors": [{"name": "author 1"}],
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "",
            "authors": [{"name": "author 1"}],
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
    ],
    indirect=["details_response"],
)
async def test_details_raises_error_when_title_missing(sut):
    with pytest.raises(ValueError) as verr_proxy:
        await sut.details("123/456")

    assert str(verr_proxy.value) == "paper title missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details_response",
    [
        {
            "title": "a title",
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "a title",
            "authors": None,
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "a title",
            "authors": [],
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "a title",
            "authors": [{"name": None}],
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "a title",
            "authors": [{"name1": "author 1"}],
            "abstract": "an abstract",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
    ],
    indirect=["details_response"],
)
async def test_details_raises_error_when_authors_missing(sut):
    with pytest.raises(ValueError) as verr_proxy:
        await sut.details("123/456")

    assert str(verr_proxy.value) == "paper authors missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details_response",
    [
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "abstract": "",
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
        {
            "title": "a title",
            "authors": [{"name": "author 1"}],
            "abstract": None,
            "references": [{"externalIds": {"DOI": "123/456"}}],
        },
    ],
    indirect=["details_response"],
)
async def test_details_raises_error_when_abstract_missing(sut):
    result = await sut.details("123/456")

    assert result.abstract == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "auth_token,expected_api_key",
    [(None, None), ("", None), ("abc", "abc")],
    indirect=["auth_token"],
)
async def test_details_calls_api_endpoint_as_expected(
    sut, request_handler, expected_api_key
):
    await sut.details("123/456")

    assert len(request_handler.call_args_list) == 1
    request = request_handler.call_args_list[0].args[0]
    assert request.url.path == "/graph/v1/paper/DOI:123/456"
    assert request.method == "GET"
    assert request.headers.get("x-api-key") == expected_api_key


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "doi", ["123/456", "doi:123/456", "DOI:123/456", "dOi:123/456"]
)
async def test_details_handles_doi_str_variations(sut, request_handler, doi):
    await sut.details(doi)

    request = request_handler.call_args_list[0].args[0]
    assert request.url.path == "/graph/v1/paper/DOI:123/456"
