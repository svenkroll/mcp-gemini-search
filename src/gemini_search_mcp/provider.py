"""Domain provider boundary per ADR 0009.

Only the standard library and pydantic may be imported here. Gemini SDK types,
grounding steps and transport details stay inside the adapter, so tools and
server code depend on this interface instead of on a concrete provider.
"""

from dataclasses import dataclass, field
from typing import Literal, Protocol, runtime_checkable

ProviderErrorKind = Literal["unavailable", "rejected", "internal"]
RetrievalStatus = Literal["retrieved", "unsafe", "failed"]


@dataclass(frozen=True, slots=True)
class Usage:
    """Token figures reported by the provider, if any."""

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """A grounded source cited in an answer."""

    url: str
    title: str
    start_index: int
    end_index: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Outcome of a provider search call."""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""


@dataclass(frozen=True, slots=True)
class Retrieval:
    """Outcome of retrieving a single URL for URL analysis."""

    url: str
    status: RetrievalStatus


@dataclass(frozen=True, slots=True)
class UrlAnalysisResult:
    """Outcome of a provider URL analysis call."""

    answer: str
    retrievals: list[Retrieval] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""


class ProviderError(Exception):
    """Provider failure with a stable kind for tools and logging.

    ``unavailable`` covers exhausted retries and timeouts, ``rejected`` a
    request the provider refused, ``internal`` an unexpected provider fault.
    The message stays generic; details belong in the log, not in the message.
    """

    def __init__(self, kind: ProviderErrorKind, message: str = "") -> None:
        super().__init__(message or f"provider error: {kind}")
        self.kind = kind


@runtime_checkable
class SearchProvider(Protocol):
    """Provider operations required by the tools."""

    async def search(self, query: str) -> SearchResult: ...

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult: ...


__all__ = [
    "Citation",
    "ProviderError",
    "ProviderErrorKind",
    "Retrieval",
    "RetrievalStatus",
    "SearchProvider",
    "SearchResult",
    "UrlAnalysisResult",
    "Usage",
]
