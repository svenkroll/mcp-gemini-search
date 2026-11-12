"""Domain provider boundary between tool logic and the Gemini backend (ADR 0009).

This module holds the provider interface, its data objects and
:class:`ProviderError` exactly as in ADR 0009, plus a scripted fake for unit
tests. It may import only the standard library and pydantic; in particular it
must never import ``fastmcp`` or ``google.genai``. Gemini-specific SDK types,
grounding steps and transport details stay inside the adapter.
"""

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

ProviderErrorKind = Literal["unavailable", "rejected", "internal"]
"""Kind of a provider failure.

``unavailable`` after exhausted retries or timeout, ``rejected`` for input the
provider refuses, ``internal`` for unexpected failures (also used by
:class:`FakeProvider` when its script is exhausted).
"""

RetrievalStatus = Literal["retrieved", "unsafe", "failed"]
"""Outcome of a single URL retrieval during an ``analyze_url`` call."""


class ProviderError(Exception):
    """Failure of a provider call (ADR 0009).

    Attributes:
        kind: one of ``unavailable``, ``rejected`` or ``internal``;
            ``unavailable`` is raised after exhausted retries or a timeout.
        message: optional human-readable detail; ``str(exc)`` returns it and
            falls back to ``kind`` when empty.

    Tool logic maps the kind to the error codes of ADR 0007 and never lets the
    message reach a client.
    """

    def __init__(self, kind: ProviderErrorKind, message: str = "") -> None:
        self.kind = kind
        self.message = message
        super().__init__(message or kind)

    def __str__(self) -> str:
        return self.message or self.kind


@dataclass(frozen=True, slots=True)
class Usage:
    """Token usage of one provider call, as reported by the API metadata.

    Both figures are ``None`` when the provider does not report them.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    """Grounded citation inside a search answer (ADR 0003)."""

    url: str
    title: str
    start_index: int
    end_index: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Result of one ``search`` provider call (ADR 0003)."""

    answer: str
    citations: list[Citation]
    search_queries: list[str]
    usage: Usage
    model: str


@dataclass(frozen=True, slots=True)
class Retrieval:
    """Outcome of retrieving one URL during ``analyze_url`` (ADR 0004)."""

    url: str
    status: RetrievalStatus


@dataclass(frozen=True, slots=True)
class UrlAnalysisResult:
    """Result of one ``analyze_url`` provider call (ADR 0004)."""

    answer: str
    retrievals: list[Retrieval]
    usage: Usage
    model: str


class SearchProvider(Protocol):
    """Domain interface for both provider operations (ADR 0009).

    Implemented by the Gemini adapter; unit tests use :class:`FakeProvider`.
    """

    async def search(self, query: str) -> SearchResult:
        """Answer a search query with grounded citations."""
        ...

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        """Answer a question about the content of one URL."""
        ...


class FakeProvider:
    """Scripted provider double for unit tests (ADR 0009).

    Each operation has its own script of preset outcomes, consumed one per
    call in construction order: a result object is returned, a preset
    :class:`ProviderError` is raised. Calling an operation whose script is
    exhausted raises ``ProviderError("internal", ...)``.

    Args:
        search_outcomes: preset outcomes for ``search``, in call order.
        analyze_url_outcomes: preset outcomes for ``analyze_url``, in call
            order.

    Needs no network access and never contacts Gemini.
    """

    def __init__(
        self,
        search_outcomes: Sequence[SearchResult | ProviderError] = (),
        analyze_url_outcomes: Sequence[UrlAnalysisResult | ProviderError] = (),
    ) -> None:
        self._search_outcomes: deque[SearchResult | ProviderError] = deque(search_outcomes)
        self._analyze_url_outcomes: deque[UrlAnalysisResult | ProviderError] = deque(
            analyze_url_outcomes,
        )

    async def search(self, query: str) -> SearchResult:
        """Consume the next preset ``search`` outcome.

        Returns the next preset :class:`SearchResult`; raises the next preset
        :class:`ProviderError` if the next outcome is one; raises
        ``ProviderError("internal")`` when more ``search`` calls happen than
        outcomes were preset.
        """
        raise NotImplementedError

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        """Consume the next preset ``analyze_url`` outcome.

        Returns the next preset :class:`UrlAnalysisResult`; raises the next
        preset :class:`ProviderError` if the next outcome is one; raises
        ``ProviderError("internal")`` when more ``analyze_url`` calls happen
        than outcomes were preset.
        """
        raise NotImplementedError
