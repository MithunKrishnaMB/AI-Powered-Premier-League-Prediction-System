"""Shared deterministic health probes for API tests."""

from dataclasses import dataclass

from pl_platform.api.health import DependencyHealth, DependencyName


@dataclass(frozen=True, slots=True)
class StaticProbe:
    """Return one configured result or raise a configured exception."""

    name: DependencyName
    result: DependencyHealth | None = None
    error: Exception | None = None

    def check(self) -> DependencyHealth:
        if self.error is not None:
            raise self.error
        if self.result is None:
            raise AssertionError("static probe requires a result")
        return self.result
