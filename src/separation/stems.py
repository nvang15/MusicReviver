"""Extensible representation of musical stem types."""

from __future__ import annotations

from typing import ClassVar


class StemType(str):
    """A normalized stem name with a core set of initially supported values.

    Unlike a closed enum, this value object accepts new, meaningful names so the
    pipeline can support specialized instruments without changing its data model.
    """

    KNOWN_NAMES: ClassVar[frozenset[str]] = frozenset(
        {"vocals", "drums", "bass", "guitar", "piano", "other"}
    )

    def __new__(cls, value: str) -> "StemType":
        if not isinstance(value, str):
            raise TypeError("Stem type must be a string.")
        normalized = value.strip().lower().replace(" ", "_")
        if not normalized:
            raise ValueError("Stem type cannot be empty.")
        if not all(part.isalnum() for part in normalized.split("_")):
            raise ValueError("Stem type may contain only letters, numbers, spaces, and underscores.")
        return super().__new__(cls, normalized)

    @property
    def is_known(self) -> bool:
        """Return whether this stem belongs to the initial supported set."""
        return self in self.KNOWN_NAMES


StemType.VOCALS = StemType("vocals")
StemType.DRUMS = StemType("drums")
StemType.BASS = StemType("bass")
StemType.GUITAR = StemType("guitar")
StemType.PIANO = StemType("piano")
StemType.OTHER = StemType("other")
