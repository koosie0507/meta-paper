import httpx

from meta_paper.search import SemanticScholarQueryParameters, QueryParameters


def test_semantic_scholar_query_parameters_factory_method():
    assert isinstance(
        QueryParameters.semantic_scholar(),
        SemanticScholarQueryParameters
    )


def test_semantic_scholar_query_title():
    sut = SemanticScholarQueryParameters().title("abc")

    actual = sut.make()

    assert isinstance(actual, httpx.QueryParams)
    assert actual.get("query") == "abc"