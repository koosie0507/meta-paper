from abc import ABCMeta, abstractmethod
from typing import Any, TypeVar, Generic

import httpx


T = TypeVar("T")


class QueryParameters(Generic[T], metaclass=ABCMeta):
    def __init__(self):
        self._filters = {}

    def title(self, value: str) -> "QueryParameters":
        self._filters["title"] = value
        return self

    @classmethod
    def semantic_scholar(cls):
        return SemanticScholarQueryParameters()

    @abstractmethod
    def make(self) -> T:
        pass


class SemanticScholarQueryParameters(QueryParameters[httpx.QueryParams]):
    def make(self) -> httpx.QueryParams:
        return httpx.QueryParams(query=self._filters["title"])
