"""Readable export failures."""


class ExportError(RuntimeError):
    pass


class ExportCancelled(ExportError):
    pass
