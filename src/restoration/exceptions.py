"""Readable restoration planning and processing errors."""


class RestorationError(Exception):
    """Base class for expected restoration failures."""


class RestorationOutputExistsError(RestorationError):
    """Raised when restoration output exists without explicit replacement."""


class NoStemsError(RestorationError):
    """Raised when restoration is requested before stem separation."""


class RestorationProcessingError(RestorationError):
    """Raised when a planned DSP action cannot be completed safely."""
