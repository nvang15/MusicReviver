"""Qt signals around the independent export API."""
import threading
import traceback
from PySide6.QtCore import QObject, Signal, Slot
from src.exporting import ExportCancelled, export_files


class ExportWorker(QObject):
    progress = Signal(object)
    completed = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)
    finished = Signal()

    def __init__(self, files, config, runner=export_files):
        super().__init__()
        self.files, self.config, self.runner = files, config, runner
        self.token = threading.Event()

    def request_cancel(self):
        self.token.set()

    @Slot()
    def run(self):
        try:
            result = self.runner(self.files, self.config, progress_callback=self.progress.emit,
                                 cancelled=self.token.is_set)
        except ExportCancelled as exc:
            self.cancelled.emit(str(exc))
        except Exception as exc:
            self.failed.emit(str(exc), traceback.format_exc())
        else:
            self.completed.emit(result)
        finally:
            self.finished.emit()
