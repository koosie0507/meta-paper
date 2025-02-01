import itertools
import json
import logging
import sys
from http import HTTPStatus
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import HTTPStatusError
from tenacity import RetryError

from meta_paper.adapters._semantic_scholar import SemanticScholarAdapter
from meta_paper.search import QueryParameters


EXPECTED_PAPER_DETAIL_FIELDS = "externalIds,title,authors,references.externalIds,abstract,isOpenAccess,openAccessPdf"


def new_detail(remove=None, **kwargs):
    result = {
        "externalIds": {
            "DOI": "234/567",
        },
        "title": "a title",
        "authors": [{"name": "author 1"}],
        "abstract": "an abstract",
        "references": [{"externalIds": {"DOI": "789/123"}}],
        "isOpenAccess": True,
        "openAccessPdf": {
            "url": "https://www.aclweb.org/anthology/2020.acl-main.447.pdf",
            "status": "HYBRID",
        },
    }
    result.update(kwargs)
    for key in remove or []:
        if key in result:
            del result[key]
    return result


@pytest.fixture
def search_response(request):
    json_data = {"data": []}
    if hasattr(request, "param"):
        json_data = {"data": [request.param]}
    return httpx.Response(200, json=json_data)


@pytest.fixture
def valid_detail():
    return new_detail()


@pytest.fixture
def details_response(request, valid_detail):
    json_data = valid_detail
    if hasattr(request, "param"):
        json_data = request.param
    return httpx.Response(200, json=json_data)


@pytest.fixture
def batch_response(request, valid_detail):
    json_data = [valid_detail]
    if hasattr(request, "param"):
        json_data = request.param
    return httpx.Response(200, json=json_data)


@pytest.fixture
def request_handler(search_response, details_response, batch_response):
    def _handler(req):
        if req.method == "POST":
            return batch_response
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
    assert search_request.url.path == "/graph/v1/paper/search"
    assert search_request.method == "GET"
    assert search_request.url.params.get("fields") == "title,externalIds,authors"
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
    result = await sut.get_one("123/456")

    assert result.doi == "DOI:234/567"
    assert result.title == "a title"
    assert result.authors == ["author 1"]
    assert result.references == ["DOI:789/123"]
    assert result.abstract == "an abstract"
    assert result.has_pdf
    assert result.pdf_url == "https://www.aclweb.org/anthology/2020.acl-main.447.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details_response",
    [new_detail(remove=["title"]), new_detail(title=None), new_detail(title="")],
    indirect=["details_response"],
)
async def test_details_raises_error_when_title_missing(sut):
    with pytest.raises(ValueError) as verr_proxy:
        await sut.get_one("123/456")

    assert str(verr_proxy.value) == "paper title missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details_response",
    [
        new_detail(remove=["authors"]),
        new_detail(authors=None),
        new_detail(authors=[]),
        new_detail(authors=[{}]),
        new_detail(authors=[{"name": None}]),
        new_detail(authors=[{"name": ""}]),
    ],
    indirect=["details_response"],
)
async def test_details_raises_error_when_authors_missing(sut):
    with pytest.raises(ValueError) as verr_proxy:
        await sut.get_one("123/456")

    assert str(verr_proxy.value) == "paper authors missing"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "details_response",
    [
        new_detail(remove=["abstract"]),
        new_detail(abstract=None),
    ],
    indirect=["details_response"],
)
async def test_details_raises_error_when_abstract_missing(sut):
    result = await sut.get_one("123/456")

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
    await sut.get_one("123/456")

    assert len(request_handler.call_args_list) == 1
    request = request_handler.call_args_list[0].args[0]
    assert request.url.path == "/graph/v1/paper/DOI:123/456"
    assert request.url.params.get("fields") == EXPECTED_PAPER_DETAIL_FIELDS
    assert request.method == "GET"
    assert request.headers.get("x-api-key") == expected_api_key


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "doi", ["123/456", "doi:123/456", "DOI:123/456", "dOi:123/456"]
)
async def test_details_handles_doi_str_variations(sut, request_handler, doi):
    await sut.get_one(doi)

    request = request_handler.call_args_list[0].args[0]
    assert request.url.path == "/graph/v1/paper/DOI:123/456"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "dois,expected",
    [
        (["123/456", "doi:789/123"], ["DOI:123/456", "DOI:789/123"]),
        ([None, "doi:789/123"], ["DOI:789/123"]),
        (["DOI:123/456", "doi:789/123"], ["DOI:123/456", "DOI:789/123"]),
        (["123/456", 123], ["DOI:123/456", "DOI:123"]),
    ],
)
async def test_get_many_calls_api_endpoint_as_expected(
    sut, request_handler, dois, expected
):
    await sut.get_many(dois)

    assert len(request_handler.call_args_list) == 1
    request = request_handler.call_args_list[0].args[0]
    assert request.method == "POST"
    assert request.url.path == "/graph/v1/paper/batch"
    assert request.url.params.get("fields") == EXPECTED_PAPER_DETAIL_FIELDS
    request_body = json.loads(request.content)
    assert "ids" in request_body
    assert request_body["ids"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("identifiers", [None, [], [None]])
async def test_get_many_does_not_call_api_if_identifiers_are_not_supplied(
    sut, request_handler, identifiers
):
    await sut.get_many(identifiers)

    assert len(request_handler.call_args_list) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "batch_response",
    [
        [
            new_detail(remove=["title"], externalIds={"DOI": "123/456"}),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, title=None),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, title=""),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
    ],
    indirect=["batch_response"],
)
async def test_get_many_handles_missing_titles_as_expected(sut, request_handler):
    result = list(await sut.get_many(["123/456", "789/123"]))

    assert len(result) == 1
    assert result[0].doi == "DOI:789/123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "batch_response",
    [
        [
            new_detail(remove=["authors"], externalIds={"DOI": "123/456"}),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, authors=None),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, authors=[]),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, authors=[None]),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, authors=[""]),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
    ],
    indirect=["batch_response"],
)
async def test_get_many_handles_missing_authors_as_expected(sut, request_handler):
    result = list(await sut.get_many(["123/456", "789/123"]))

    assert len(result) == 1
    assert result[0].doi == "DOI:789/123"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "batch_response",
    [
        [
            new_detail(remove=["references"], externalIds={"DOI": "123/456"}),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, references=None),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, references=[]),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, references=[None]),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(externalIds={"DOI": "123/456"}, references=[{}]),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(
                externalIds={"DOI": "123/456"}, references=[{"externalIds": None}]
            ),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(
                externalIds={"DOI": "123/456"}, references=[{"externalIds": {}}]
            ),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(
                externalIds={"DOI": "123/456"},
                references=[{"externalIds": {"DOI": None}}],
            ),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
        [
            new_detail(
                externalIds={"DOI": "123/456"},
                references=[{"externalIds": {"DOI": ""}}],
            ),
            new_detail(externalIds={"DOI": "789/123"}),
        ],
    ],
    indirect=["batch_response"],
)
async def test_get_many_handles_missing_references_as_expected(sut, request_handler):
    result = list(await sut.get_many(["123/456", "789/123"]))

    assert len(result) == 2
    assert result[0].doi == "DOI:123/456"
    assert len(result[0].references) == 0
    assert result[1].doi == "DOI:789/123"
    assert len(result[1].references) == 1
