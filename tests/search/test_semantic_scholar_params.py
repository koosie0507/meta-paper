import httpx

from meta_paper.search import QueryParameters


def test_title():
    sut = QueryParameters().title("abc")

    actual = sut.semantic_scholar()

    assert isinstance(actual, httpx.QueryParams)
    assert actual.get("query") == "abc"


def test_empty_params():
    sut = QueryParameters()

    actual = sut.semantic_scholar()

    assert isinstance(actual, httpx.QueryParams)
    assert "query" not in actual
