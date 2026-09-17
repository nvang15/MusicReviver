"""Mastering-specific errors suitable for CLI and GUI callers."""


class MasteringError(RuntimeError):
    """Base mastering failure."""


class NoMixError(MasteringError):
    """A valid Milestone 6 mix was not available."""


class MasterOutputExistsError(MasteringError):
    """Master output is protected from implicit replacement."""


class MasteringSafetyError(MasteringError):
    """Rendered audio failed a safety invariant."""
