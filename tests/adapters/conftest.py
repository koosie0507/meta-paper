import httpx
import pytest

from meta_paper.search import QueryParameters


@pytest.fixture
def http_client(request, request_handler):
    handler = request.param if hasattr(request, "param") else request_handler
    return httpx.AsyncClient(transport=httpx.MockTransport(handler=handler))


@pytest.fixture
def auth_token(request):
    return request.param if hasattr(request, "param") else None


@pytest.fixture
def query_parameters():
    return QueryParameters()
