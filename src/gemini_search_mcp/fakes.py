"""In-memory test double for the provider boundary.

``FakeProvider`` serves preset results or raises preset ``ProviderError`` kinds
per call, so unit tests need no network access and no Gemini key. It is a test
double, never shipped behaviour for the server.
"""

from collections.abc import Iterable, Sequence

from gemini_search_mcp.provider import (
    ProviderError,
    SearchResult,
    UrlAnalysisResult,
)

Outcome = SearchResult | UrlAnalysisResult | ProviderError


def _outcome_at(outcomes: Sequence[Outcome], index: int) -> Outcome:
    # The last preset outcome repeats once the sequence is exhausted.
    return outcomes[min(index, len(outcomes) - 1)]


class FakeProvider:
    """``SearchProvider`` that reports preset outcomes instead of calling out."""

    def __init__(
        self,
        *,
        search_outcomes: Iterable[Outcome] = (),
        analyze_outcomes: Iterable[Outcome] = (),
    ) -> None:
        self._search_outcomes = list(search_outcomes)
        self._analyze_outcomes = list(analyze_outcomes)
        self._search_calls = 0
        self._analyze_calls = 0
        self.search_queries: list[str] = []
        self.analyze_requests: list[tuple[str, str]] = []

    def set_search_outcomes(self, *outcomes: Outcome) -> None:
        """Replace the preset search outcomes for subsequent calls."""
        self._search_outcomes = list(outcomes)
        self._search_calls = 0

    def set_analyze_outcomes(self, *outcomes: Outcome) -> None:
        """Replace the preset URL analysis outcomes for subsequent calls."""
        self._analyze_outcomes = list(outcomes)
        self._analyze_calls = 0

    def _next_search(self) -> SearchResult:
        if not self._search_outcomes:
            raise AssertionError("FakeProvider has no preset search outcome")
        outcome = _outcome_at(self._search_outcomes, self._search_calls)
        self._search_calls += 1
        if isinstance(outcome, ProviderError):
            raise outcome
        if not isinstance(outcome, SearchResult):
            raise TypeError(f"search outcome must be SearchResult or ProviderError: {outcome!r}")
        return outcome

    def _next_analyze(self) -> UrlAnalysisResult:
        if not self._analyze_outcomes:
            raise AssertionError("FakeProvider has no preset URL analysis outcome")
        outcome = _outcome_at(self._analyze_outcomes, self._analyze_calls)
        self._analyze_calls += 1
        if isinstance(outcome, ProviderError):
            raise outcome
        if not isinstance(outcome, UrlAnalysisResult):
            raise TypeError(
                f"URL analysis outcome must be UrlAnalysisResult or ProviderError: {outcome!r}"
            )
        return outcome

    async def search(self, query: str) -> SearchResult:
        self.search_queries.append(query)
        return self._next_search()

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        self.analyze_requests.append((url, question))
        return self._next_analyze()


__all__ = ["FakeProvider"]
