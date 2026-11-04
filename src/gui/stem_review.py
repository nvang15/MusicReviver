"""Waveform-based, non-destructive multistem review workspace."""
from __future__ import annotations
import re, shutil, tempfile, traceback
from pathlib import Path
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt, QEvent, QSignalBlocker
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)
from src.config import TEMP_DIR
from src.exporting import AudioFormat, ExportConfig, export_files
from src.workspace import load_workspace, save_workspace, measure_activity, render_mix
from src.gui.audio_transport import create_stem_transport
from src.gui.waveform import WaveformWidget, combine_envelopes, extract_waveform

def safe_export_label(label):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", label).strip(" ."); return value[:120] or "Stem"
def format_time(ms):
    seconds = max(0, ms // 1000); return f"{seconds // 60:02d}:{seconds % 60:02d}"

class ReviewWorker(QObject):
    completed = Signal(object); failed = Signal(str, str); finished = Signal()
    def __init__(self, operation): super().__init__(); self.operation = operation
    @Slot()
    def run(self):
        try: self.completed.emit(self.operation())
        except Exception as exc: self.failed.emit(str(exc), traceback.format_exc())
        finally: self.finished.emit()

class StemRow(QWidget):
    selectionChanged = Signal(str, bool); soloChanged = Signal(str, bool); muteChanged = Signal(str, bool)
    renameSaved = Signal(str, str); seekRequested = Signal(int)
    def __init__(self, stem, envelope, duration, selected=False, parent=None):
        super().__init__(parent); self.stem_id = stem.id; layout = QHBoxLayout(self); layout.setContentsMargins(3,3,3,3)
        self.name_stack = QStackedWidget(); display = QWidget(); dl = QHBoxLayout(display); dl.setContentsMargins(0,0,0,0)
        self.name_button = QPushButton(stem.display_label); self.name_button.setCheckable(True); self.name_button.setAutoExclusive(False); self.name_button.setAutoDefault(False); self.name_button.setChecked(selected); self.name_button.setMinimumWidth(150)
        self.edit_button = QPushButton("✎"); self.edit_button.setToolTip("Rename display label"); self.edit_button.setFixedWidth(34); dl.addWidget(self.name_button); dl.addWidget(self.edit_button)
        editor = QWidget(); el = QHBoxLayout(editor); el.setContentsMargins(0,0,0,0); self.edit = QLineEdit(stem.display_label); self.save_button = QPushButton("✓"); self.cancel_button = QPushButton("×")
        self.save_button.setFixedWidth(32); self.cancel_button.setFixedWidth(32); el.addWidget(self.edit); el.addWidget(self.save_button); el.addWidget(self.cancel_button)
        self.name_stack.addWidget(display); self.name_stack.addWidget(editor); self.name_stack.setFixedWidth(230); layout.addWidget(self.name_stack)
        self.solo_button, self.mute_button = QPushButton("S"), QPushButton("M")
        for button in (self.solo_button, self.mute_button): button.setCheckable(True); button.setAutoExclusive(False); button.setAutoDefault(False); button.setFixedWidth(36)
        self.solo_button.setChecked(stem.soloed); self.mute_button.setChecked(stem.muted); layout.addWidget(self.solo_button); layout.addWidget(self.mute_button)
        self.status = QLabel("Likely inactive" if stem.likely_inactive else ""); self.status.setFixedWidth(92); layout.addWidget(self.status)
        self.waveform = WaveformWidget(); self.waveform.set_envelope(envelope); self.waveform.set_duration(duration); layout.addWidget(self.waveform, 1)
        self.name_button.clicked.connect(lambda value: self.selectionChanged.emit(self.stem_id, value)); self.solo_button.clicked.connect(lambda value: self.soloChanged.emit(self.stem_id, value)); self.mute_button.clicked.connect(lambda value: self.muteChanged.emit(self.stem_id, value))
        self.edit_button.clicked.connect(self.begin_rename); self.save_button.clicked.connect(self.save_rename); self.cancel_button.clicked.connect(self.cancel_rename); self.edit.returnPressed.connect(self.save_rename); self.edit.installEventFilter(self); self.waveform.seekRequested.connect(self.seekRequested)
        if stem.likely_inactive: self.setObjectName("inactiveStemRow"); self.waveform.dimmed = True; self.setStyleSheet("#inactiveStemRow QLabel { color: #9299a3; }")
    def begin_rename(self): self.edit.setText(self.name_button.text()); self.name_stack.setCurrentIndex(1); self.edit.setFocus(); self.edit.selectAll()
    def save_rename(self):
        label = self.edit.text().strip()
        if label: self.name_button.setText(label); self.name_stack.setCurrentIndex(0); self.renameSaved.emit(self.stem_id, label)
    def cancel_rename(self): self.name_stack.setCurrentIndex(0)
    def eventFilter(self, watched, event):
        if watched is self.edit and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape: self.cancel_rename(); return True
        return super().eventFilter(watched, event)
    def set_position(self, value): self.waveform.set_position(value)

class StemReviewWindow(QDialog):
    def __init__(self, project: Path, parent=None, transport_factory=create_stem_transport):
        super().__init__(parent); self.project = Path(project).resolve(); self._worker_thread = self._worker = None; self._completion_callback = None; self._close_when_finished = False
        self.selected_ids, self.envelopes, self.rows = set(), {}, {}; self.workspace = load_workspace(self.project); self.transport_factory = transport_factory
        self.setWindowTitle("Stem Review — " + self.project.name); self.resize(1100,760); self.transport = self._create_transport(); self._build(); self._render_rows(); self._load_waveforms(); self.transport.seek_ms(self.workspace.position_ms); self._update_audible()
    def _paths(self): return {stem.id: self.workspace.source_path(stem.id) for stem in self.workspace.stems}
    def _create_transport(self): return self.transport_factory(self._paths(), self)
    def _build(self):
        layout = QVBoxLayout(self); top = QHBoxLayout(); top.addWidget(QLabel("Source:")); self.source = QComboBox(); self.source.addItem("Separated", "separated")
        if (self.project/"restored").is_dir(): self.source.addItem("Restored", "restored")
        top.addWidget(self.source); top.addStretch(); layout.addLayout(top); tr = QHBoxLayout(); self.play_button = QPushButton("▶ Play"); self.stop_button = QPushButton("Stop"); self.back_button = QPushButton("−5 sec"); self.forward_button = QPushButton("+5 sec")
        self.play_button.setEnabled(False)
        for button in (self.play_button,self.stop_button,self.back_button,self.forward_button): tr.addWidget(button)
        tr.addStretch(); self.time = QLabel("00:00 / "+format_time(self.transport.duration_ms)); tr.addWidget(self.time); layout.addLayout(tr)
        self.combined_waveform = WaveformWidget(large=True); self.combined_waveform.set_duration(self.transport.duration_ms); layout.addWidget(self.combined_waveform); self.audible_label = QLabel("Audible: all unmuted stems"); layout.addWidget(self.audible_label)
        self.scroll=QScrollArea(); self.scroll.setWidgetResizable(True); self.rows_host=QWidget(); self.rows_layout=QVBoxLayout(self.rows_host); self.scroll.setWidget(self.rows_host); layout.addWidget(self.scroll,1)
        actions=QHBoxLayout()
        for text,callback in (("Clear Selection",self.clear_selection),("Clear Solos",self.clear_solos),("Clear Mutes",self.clear_mutes),("Create Group",self.create_group),("Export Selected",self.export_selected)):
            button=QPushButton(text); button.clicked.connect(callback); actions.addWidget(button)
        actions.addStretch(); layout.addLayout(actions); layout.addWidget(QLabel("Groups")); self.groups=QListWidget(); self.groups.setMaximumHeight(100); layout.addWidget(self.groups); ga=QHBoxLayout()
        for text,callback in (("Audition Group",self.audition_group),("Rename Group",self.rename_group),("Ungroup",self.ungroup),("Export Group",self.export_group)):
            button=QPushButton(text); button.clicked.connect(callback); ga.addWidget(button)
        ga.addStretch(); layout.addLayout(ga); self.status=QLabel(""); layout.addWidget(self.status)
        self.play_button.clicked.connect(self.transport.play_pause); self.stop_button.clicked.connect(self.transport.stop); self.back_button.clicked.connect(lambda:self.jump(-5000)); self.forward_button.clicked.connect(lambda:self.jump(5000)); self.combined_waveform.seekRequested.connect(self.seek); self.transport.positionChanged.connect(self._position); self.transport.playingChanged.connect(self._playing_changed); self.transport.audioError.connect(self._playback_error); self.source.currentIndexChanged.connect(self.switch_source)
    def _render_rows(self):
        while self.rows_layout.count():
            widget=self.rows_layout.takeAt(0).widget()
            if widget: widget.hide(); widget.setParent(None); widget.deleteLater()
        self.rows={}
        for stem in sorted(self.workspace.stems,key=lambda s:(s.likely_inactive,s.source.lower())):
            row=StemRow(stem,self.envelopes.get(stem.id),self.transport.duration_ms,stem.id in self.selected_ids); row.selectionChanged.connect(self._selection_changed); row.soloChanged.connect(lambda sid,value:self._toggle(sid,"soloed",value)); row.muteChanged.connect(lambda sid,value:self._toggle(sid,"muted",value)); row.renameSaved.connect(self._rename_saved); row.seekRequested.connect(self.seek); self.rows_layout.addWidget(row); self.rows[stem.id]=row
        self.rows_layout.addStretch(); self.groups.clear()
        for group in self.workspace.groups:
            item=QListWidgetItem(f"{group.display_label} ({len(group.members)} stems)"); item.setData(Qt.ItemDataRole.UserRole,group.id); self.groups.addItem(item)
    def _load_waveforms(self):
        stems=list(self.workspace.stems); cache=self.project/"workspace"/"waveforms"
        def operation():
            results={}
            for stem in stems:
                envelope,hit=extract_waveform(self.workspace.source_path(stem.id),cache); activity=None if stem.measurements else measure_activity(self.workspace.source_path(stem.id)); results[stem.id]=(envelope,activity,hit)
            return results
        self._run(operation,self._waveforms_ready,"Preparing waveforms…")
    def _waveforms_ready(self,results):
        for sid,(envelope,activity,hit) in results.items():
            self.envelopes[sid]=envelope
            if activity:
                stem=self.workspace._stem(sid); stem.likely_inactive=activity.likely_inactive; stem.measurements={"rms_dbfs":activity.rms_dbfs,"peak_dbfs":activity.peak_dbfs,"active_fraction":activity.active_fraction}
        self.transport.set_peaks({k:v.peak for k,v in self.envelopes.items()}); self.play_button.setEnabled(True); self._persist(); self._render_rows(); self._update_audible(); self.status.setText("")
    def _selection_changed(self,sid,selected):
        self.selected_ids.add(sid) if selected else self.selected_ids.discard(sid); self._sync_row_states(); self._update_audible()
    def _toggle(self,sid,attribute,value): setattr(self.workspace._stem(sid),attribute,value); self._persist(); self._sync_row_states(); self._update_audible()
    def _sync_row_states(self):
        """Reflect model state without feeding programmatic changes back as clicks."""
        for sid,row in self.rows.items():
            stem=self.workspace._stem(sid)
            for button,value in ((row.name_button,sid in self.selected_ids),(row.solo_button,stem.soloed),(row.mute_button,stem.muted)):
                blocker=QSignalBlocker(button); button.setChecked(value); del blocker
    def audible_ids(self): return self.workspace.audible_ids(tuple(self.selected_ids))
    def _update_audible(self):
        ids=self.audible_ids(); self.transport.set_audible(ids); self.combined_waveform.set_envelope(combine_envelopes([self.envelopes[k] for k in ids if k in self.envelopes])); labels=[self.workspace._stem(k).display_label for k in ids]; self.audible_label.setText("Audible: "+(", ".join(labels) if labels else "silence"))
    def clear_selection(self):
        self.selected_ids.clear(); self._sync_row_states(); self._update_audible()
    def clear_solos(self): self.workspace.clear_solos(); self._persist(); self._sync_row_states(); self._update_audible()
    def clear_mutes(self): self.workspace.clear_mutes(); self._persist(); self._sync_row_states(); self._update_audible()
    def _rename_saved(self,sid,label): self.workspace.rename_stem(sid,label); self._persist(); self._update_audible()
    def _persist(self): self.workspace.position_ms=self.transport.position_ms; save_workspace(self.workspace)
    def seek(self,value): self.transport.seek_ms(value)
    def jump(self,amount): self.seek(max(0,min(self.transport.duration_ms,self.transport.position_ms+amount)))
    def _position(self,value):
        self.time.setText(f"{format_time(value)} / {format_time(self.transport.duration_ms)}"); self.combined_waveform.set_position(value)
        for row in self.rows.values(): row.set_position(value)
    def _playing_changed(self,playing): self.play_button.setText("⏸ Pause" if playing else "▶ Play")
    def _playback_error(self, message):
        self.status.setText(message)
        self.play_button.setText("▶ Play")
    def switch_source(self):
        position=self.transport.position_ms; self.play_button.setEnabled(False); self.play_button.clicked.disconnect(); self.stop_button.clicked.disconnect(); self.transport.close(); self.workspace=load_workspace(self.project,self.source.currentData()); self.selected_ids.clear(); self.envelopes.clear(); self.transport=self._create_transport(); self.transport.positionChanged.connect(self._position); self.transport.playingChanged.connect(self._playing_changed); self.transport.audioError.connect(self._playback_error); self.play_button.clicked.connect(self.transport.play_pause); self.stop_button.clicked.connect(self.transport.stop); self.transport.seek_ms(position); self._render_rows(); self._load_waveforms(); self._update_audible()
    def create_group(self):
        members=list(self.selected_ids)
        if len(members)<2:return self._error("Select at least two stems to create a group.")
        label,ok=QInputDialog.getText(self,"Create group","Group name",text="Group")
        if ok:self.workspace.create_group(label,members);self._persist();self._render_rows()
    def _selected_group(self):
        item=self.groups.currentItem();return self.workspace._group(item.data(Qt.ItemDataRole.UserRole)) if item else None
    def audition_group(self):
        group=self._selected_group()
        if group:self.selected_ids=set(group.members);self._render_rows();self._update_audible()
    def rename_group(self):
        group=self._selected_group()
        if not group:return
        label,ok=QInputDialog.getText(self,"Rename group","Group name",text=group.display_label)
        if ok:self.workspace.rename_group(group.id,label);self._persist();self._render_rows()
    def ungroup(self):
        group=self._selected_group()
        if group:self.workspace.dissolve_group(group.id);self._persist();self._render_rows()
    def export_selected(self):
        ids=tuple(self.selected_ids) or self.audible_ids()
        if not ids:return self._error("No audible stems are available to export.")
        self._export(tuple(self.workspace.source_path(k) for k in ids),[self.workspace._stem(k).display_label for k in ids])
    def export_group(self):
        group=self._selected_group()
        if not group:return
        target=self.project/"workspace"/"exports"/(safe_export_label(group.display_label)+".wav");paths=tuple(self.workspace.source_path(k) for k in group.members);self._run(lambda:render_mix(paths,target),lambda result:self._export((result.path,),(group.display_label,),result.attenuation_db),"Rendering group…")
    def _export(self,paths,labels,attenuation=0.0):
        destination=QFileDialog.getExistingDirectory(self,"Export destination")
        if not destination:return
        names=["WAV 24-bit","FLAC","MP3 320","M4A/AAC 320"];chosen,ok=QInputDialog.getItem(self,"Export format","Format",names,editable=False)
        if not ok:return
        kind=dict(zip(names,(AudioFormat.WAV,AudioFormat.FLAC,AudioFormat.MP3,AudioFormat.M4A)))[chosen];TEMP_DIR.mkdir(parents=True,exist_ok=True);staging=Path(tempfile.mkdtemp(prefix="musicreviver-labels-",dir=TEMP_DIR))
        def operation():
            named=[]
            for path,label in zip(paths,labels):
                target=staging/f"{safe_export_label(self.project.name)} - {safe_export_label(label)}{path.suffix}";shutil.copyfile(path,target);named.append(target)
            try:return export_files(tuple(named),ExportConfig(Path(destination),kind,320))
            finally:shutil.rmtree(staging,ignore_errors=True)
        self._run(operation,lambda result:self.status.setText(f"Exported {len(result.files)} file(s)."+(f" Group attenuation: {attenuation:.2f} dB." if attenuation<0 else "")),"Exporting…")
    def _run(self,operation,completed,message):
        if self._worker_thread is not None:return self._error("Another review operation is still running.")
        self.status.setText(message);self._completion_callback=completed;self._worker_thread=QThread(self);self._worker=ReviewWorker(operation);self._worker.moveToThread(self._worker_thread);self._worker_thread.started.connect(self._worker.run);self._worker.completed.connect(self._worker_completed,Qt.ConnectionType.QueuedConnection);self._worker.failed.connect(self._worker_failed,Qt.ConnectionType.QueuedConnection);self._worker.finished.connect(self._worker_thread.quit);self._worker.finished.connect(self._worker.deleteLater);self._worker_thread.finished.connect(self._thread_finished,Qt.ConnectionType.QueuedConnection);self._worker_thread.start()
    @Slot(object)
    def _worker_completed(self,result):
        if self._completion_callback:self._completion_callback(result)
    @Slot(str,str)
    def _worker_failed(self,message,details):self._error(message)
    @Slot()
    def _thread_finished(self):
        thread=self._worker_thread;self._worker_thread=self._worker=None;self._completion_callback=None
        if thread:thread.deleteLater()
        if self._close_when_finished:self._close_when_finished=False;self.close()
    def _error(self,message):self.status.setText(message);QMessageBox.warning(self,"Stem Review",message)
    def closeEvent(self,event):
        if self._worker_thread is not None:self._close_when_finished=True;self.status.setText("Closing after the current operation finishes…");event.ignore();return
        self._persist();self.transport.close();event.accept()
