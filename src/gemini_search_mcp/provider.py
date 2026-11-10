"""Domain provider boundary per ADR 0009.

Tools and server depend only on this module. Gemini-specific SDK types stay in
the adapter, so a later provider change barely touches the tool contract.
"""

from dataclasses import dataclass
from typing import Literal, Protocol

ProviderErrorKind = Literal["unavailable", "rejected", "internal"]
RetrievalStatus = Literal["retrieved", "unsafe", "failed"]


@dataclass(frozen=True, slots=True, kw_only=True)
class Usage:
    """Token figures from the provider's usage metadata."""

    input_tokens: int | None
    output_tokens: int | None


@dataclass(frozen=True, slots=True, kw_only=True)
class Citation:
    """One grounded source with its position in the answer text."""

    url: str
    title: str
    start_index: int
    end_index: int


@dataclass(frozen=True, slots=True, kw_only=True)
class SearchResult:
    """Result of a ``search`` call."""

    answer: str
    citations: list[Citation]
    search_queries: list[str]
    usage: Usage
    model: str


@dataclass(frozen=True, slots=True, kw_only=True)
class Retrieval:
    """One URL retrieval with its status."""

    url: str
    status: RetrievalStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class UrlAnalysisResult:
    """Result of an ``analyze_url`` call."""

    answer: str
    retrievals: list[Retrieval]
    usage: Usage
    model: str


class ProviderError(Exception):
    """A provider call failed.

    ``unavailable`` means the backend is unavailable after exhausted retries or
    a timeout; ``rejected`` means the provider refused the request; ``internal``
    covers any other provider error.
    """

    def __init__(self, kind: ProviderErrorKind, message: str = "") -> None:
        self.kind = kind
        super().__init__(message or f"provider error: {kind}")


class SearchProvider(Protocol):
    """Backend for the two tools."""

    async def search(self, query: str) -> SearchResult: ...

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult: ...
