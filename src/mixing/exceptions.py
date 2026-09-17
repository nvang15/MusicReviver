"""Readable mixing and alignment errors."""


class MixingError(Exception):
    """Base class for expected mixing failures."""


class NoMixStemsError(MixingError):
    """Raised when no requested stem set exists."""


class StemAlignmentError(MixingError):
    """Raised when canonical stems are materially incompatible."""


class MixOutputExistsError(MixingError):
    """Raised when published mix output exists without --force."""
