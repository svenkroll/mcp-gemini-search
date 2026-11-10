"""Test doubles for the provider boundary per ADR 0009.

``FakeProvider`` replays preset results and errors per call, so unit tests need
no network access and no Gemini API key.
"""

from collections.abc import Mapping, Sequence
from typing import cast

from gemini_search_mcp.provider import (
    ProviderError,
    ProviderErrorKind,
    SearchResult,
    UrlAnalysisResult,
)

ProviderResponse = SearchResult | UrlAnalysisResult | ProviderErrorKind | ProviderError


def _resolve(preset: ProviderResponse) -> SearchResult | UrlAnalysisResult:
    if isinstance(preset, ProviderError):
        raise preset
    if isinstance(preset, str):
        raise ProviderError(preset)
    return preset


class _PresetSequence:
    """Presets consumed call by call; the last one repeats once exhausted."""

    def __init__(self, presets: Sequence[ProviderResponse], operation: str) -> None:
        self._presets = list(presets)
        self._operation = operation
        self.calls: list[tuple[str, ...]] = []

    def next(self, *arguments: str) -> SearchResult | UrlAnalysisResult:
        if not self._presets:
            raise TypeError(f"FakeProvider has no preset for {self._operation}()")
        self.calls.append(arguments)
        index = min(len(self.calls), len(self._presets)) - 1
        return _resolve(self._presets[index])


class FakeProvider:
    """``SearchProvider`` returning preset results and raising preset errors."""

    def __init__(
        self,
        *,
        search: Sequence[SearchResult | ProviderErrorKind | ProviderError] = (),
        analyze_url: Sequence[UrlAnalysisResult | ProviderErrorKind | ProviderError] = (),
    ) -> None:
        self._search = _PresetSequence(search, "search")
        self._analyze_url = _PresetSequence(analyze_url, "analyze_url")

    @property
    def calls(self) -> Mapping[str, list[tuple[str, ...]]]:
        """Recorded arguments per operation, in call order."""
        return {"search": self._search.calls, "analyze_url": self._analyze_url.calls}

    async def search(self, query: str) -> SearchResult:
        return cast("SearchResult", self._search.next(query))

    async def analyze_url(self, url: str, question: str) -> UrlAnalysisResult:
        return cast("UrlAnalysisResult", self._analyze_url.next(url, question))
