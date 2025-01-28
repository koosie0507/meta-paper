from typing import Any

import httpx


class QueryParameters:
    def __init__(self):
        self.__title = None

    def title(self, value: str) -> "QueryParameters":
        self.__title = value
        return self

    def semantic_scholar(self) -> "Any":
        result = httpx.QueryParams()
        if self.__title:
            result = result.set("query", self.__title)
        return result
