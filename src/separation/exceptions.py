"""Readable errors raised by the separation subsystem."""


class SeparationError(Exception):
    """Base class for expected separation failures."""


class BackendUnavailableError(SeparationError):
    """Raised when a requested separation backend is unavailable."""


class DeviceUnavailableError(SeparationError):
    """Raised when an explicitly requested execution device is unavailable."""


class UnknownModelError(SeparationError):
    """Raised when a requested model is not registered."""


class OutputExistsError(SeparationError):
    """Raised when valid stem output already exists and force was not requested."""


class MissingStemError(SeparationError):
    """Raised when a backend does not produce every expected stem."""
