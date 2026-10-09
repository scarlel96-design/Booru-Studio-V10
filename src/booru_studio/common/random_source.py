from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field
from typing import Protocol


class RandomSource(Protocol):
    def uniform(self, low: float, high: float) -> float: ...

    def token_bytes(self, length: int) -> bytes: ...


@dataclass(slots=True)
class SystemRandomSource:
    _rng: random.SystemRandom = field(default_factory=random.SystemRandom)

    def uniform(self, low: float, high: float) -> float:
        return self._rng.uniform(low, high)

    def token_bytes(self, length: int) -> bytes:
        if length < 0:
            raise ValueError("length must be non-negative")
        return secrets.token_bytes(length)


@dataclass(slots=True)
class DeterministicRandomSource:
    seed: int = 0
    _rng: random.Random = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def uniform(self, low: float, high: float) -> float:
        return self._rng.uniform(low, high)

    def token_bytes(self, length: int) -> bytes:
        if length < 0:
            raise ValueError("length must be non-negative")
        return bytes(self._rng.randrange(0, 256) for _ in range(length))
