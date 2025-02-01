import re


class DOIPrefixMixin:
    __DOI_RE = re.compile(r"\bdoi:\b", re.IGNORECASE | re.S)

    def _prepend_doi(self, doi: str, upper_case: bool = True) -> str:
        doi = str(doi).strip()
        prefix = "DOI:" if upper_case else "doi:"
        if doi.upper().startswith("DOI:"):
            return self.__DOI_RE.sub(prefix, doi, 1)
        return f"{prefix}{doi}"

    def _has_doi_prefix(self, doi: str) -> bool:
        return bool(self.__DOI_RE.search(doi))
