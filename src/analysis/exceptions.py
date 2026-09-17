"""Readable errors raised by the audio-analysis subsystem."""


class AnalysisError(Exception):
    """Base class for expected analysis failures."""


class UnsupportedAnalysisInputError(AnalysisError):
    """Raised when an analysis input is not a readable WAV file."""


class AnalysisOutputExistsError(AnalysisError):
    """Raised when a report exists and replacement was not requested."""
