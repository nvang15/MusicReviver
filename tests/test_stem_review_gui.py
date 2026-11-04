import os, time
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf

from src.gui.app import create_application
from PySide6.QtCore import QObject, QThread, Qt, qInstallMessageHandler
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from src.gui import stem_review
from src.gui.main_window import MainWindow
from src.gui.stem_review import ReviewWorker, StemReviewWindow, safe_export_label
from src.gui.audio_transport import NullAudioSink, StemMixDevice, StemMixTransport
from PySide6.QtMultimedia import QAudioFormat
from src.gui.waveform import WaveformWidget, extract_waveform

@pytest.fixture(scope="module")
def application():
    previous = os.environ.get("QT_QPA_PLATFORM"); os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = create_application(["stem-review-tests"]); yield app
    if previous is None: os.environ.pop("QT_QPA_PLATFORM", None)
    else: os.environ["QT_QPA_PLATFORM"] = previous

def make_project(tmp_path, names=("one", "two")):
    root = tmp_path / "song"; t = np.arange(2400) / 48000
    for i, name in enumerate(names):
        path = root / "stems" / f"{name}.wav"; path.parent.mkdir(parents=True, exist_ok=True)
        signal = .05 * np.sin(2*np.pi*(220+i*20)*t); sf.write(path, np.column_stack((signal, signal)), 48000, subtype="PCM_24")
    return root

def pump(app, condition, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if condition(): return
        time.sleep(.01)
    assert condition()

def test_dynamic_rows_construct_headlessly(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path, ("a", "b", "custom_name")))
    pump(application, lambda: window._worker_thread is None)
    assert len(window.rows) == 3 and "custom_name" in [Path(s.source).stem for s in window.workspace.stems]
    assert window._worker_thread is None and window._worker is None
    window.close()

def test_offscreen_window_never_enumerates_native_audio(application, tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError("native audio device enumeration must not occur offscreen")
    monkeypatch.setattr("src.gui.audio_transport.QMediaDevices.defaultAudioOutput", forbidden)
    window = StemReviewWindow(make_project(tmp_path))
    pump(application, lambda: window._worker_thread is None)
    assert isinstance(window.transport.sink, NullAudioSink)
    window.transport.play_pause(); assert window.transport.is_playing
    window.transport.play_pause(); assert not window.transport.is_playing
    window.transport.seek_ms(20); assert abs(window.transport.position_ms - 20) <= 1
    window.transport.stop(); assert window.transport.position_ms == 0
    window.close()

class FakeOutputDevice:
    def __init__(self, *, null=False, float_supported=True, int16_supported=True):
        self.null = null; self.float_supported = float_supported; self.int16_supported = int16_supported
    def isNull(self): return self.null
    def isFormatSupported(self, fmt):
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float: return self.float_supported
        if fmt.sampleFormat() == QAudioFormat.SampleFormat.Int16: return self.int16_supported
        return False

class FakePhysicalSink(QObject):
    def __init__(self, output, fmt, parent=None):
        super().__init__(parent); self.output = output; self.fmt = fmt; self.buffer_size = 0; self.usecs = 0
    def setBufferSize(self, value): self.buffer_size = value
    def bufferSize(self): return self.buffer_size
    def start(self, device): self.started = True
    def suspend(self): pass
    def resume(self): pass
    def stop(self): self.usecs = 0
    def processedUSecs(self): return self.usecs

def test_physical_backend_is_lazy_and_float_int16_selection_is_testable(application, tmp_path):
    paths = {p.stem:p for p in (make_project(tmp_path)/"stems").glob("*.wav")}; calls=[]
    def factory(output, fmt, parent): calls.append(fmt.sampleFormat()); return FakePhysicalSink(output, fmt, parent)
    transport = StemMixTransport(paths, sink_factory=factory, output_device_provider=lambda: FakeOutputDevice(), defer_output=True)
    assert transport.sink is None and not calls
    transport.play_pause()
    assert calls == [QAudioFormat.SampleFormat.Float] and transport.is_playing
    transport.close()
    transport = StemMixTransport(paths, sink_factory=factory,
        output_device_provider=lambda: FakeOutputDevice(float_supported=False), defer_output=True)
    transport.play_pause()
    assert calls[-1] == QAudioFormat.SampleFormat.Int16
    assert transport.device._sample_format == QAudioFormat.SampleFormat.Int16
    transport.close()

def test_no_audio_device_reports_error_without_disabling_workspace(application, tmp_path):
    paths = {p.stem:p for p in (make_project(tmp_path)/"stems").glob("*.wav")}
    transport = StemMixTransport(paths, output_device_provider=lambda: FakeOutputDevice(null=True))
    errors=[]; transport.audioError.connect(errors.append); transport.play_pause()
    assert errors == ["No audio output device is available."]
    assert transport.sink is None and not transport.is_playing
    transport.seek_ms(20); assert abs(transport.position_ms - 20) <= 1
    transport.close()

def test_no_audio_device_keeps_review_window_usable(application, tmp_path):
    def factory(paths, parent):
        return StemMixTransport(paths, parent, output_device_provider=lambda: FakeOutputDevice(null=True))
    window = StemReviewWindow(make_project(tmp_path), transport_factory=factory)
    pump(application, lambda: window._worker_thread is None)
    window.play_button.click()
    assert window.status.text() == "No audio output device is available."
    assert window.play_button.isEnabled() and not window.transport.is_playing
    first = next(iter(window.rows.values())); first.name_button.click()
    assert window.selected_ids == {first.stem_id}
    window.close()

def test_dialog_media_and_dynamic_widgets_have_gui_affinity(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path))
    pump(application, lambda: window._worker_thread is None)
    gui_thread = application.thread()
    assert window.thread() is gui_thread
    assert window.transport.sink.thread() is gui_thread
    assert window.transport.device.thread() is gui_thread
    assert window.transport.timer.thread() is gui_thread
    assert all(widget.thread() is gui_thread for widget in window.findChildren(QWidget))
    window.close()

def test_worker_completion_is_queued_to_gui_thread(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path))
    pump(application, lambda: window._worker_thread is None)
    observed = {}
    def operation():
        observed["worker"] = QThread.currentThread()
        return Path("preview.wav")
    def completed(result):
        observed["completion"] = QThread.currentThread()
        observed["result"] = result
    window._run(operation, completed, "test")
    pump(application, lambda: window._worker_thread is None)
    assert observed["worker"] is not application.thread()
    assert observed["completion"] is application.thread()
    assert observed["result"] == Path("preview.wav")
    window.close()

def test_preview_render_worker_is_non_gui_and_returns_plain_result(application, tmp_path, monkeypatch):
    window = StemReviewWindow(make_project(tmp_path))
    pump(application, lambda: window._worker_thread is None)
    source = tuple(window.workspace.source_path(s.id) for s in window.workspace.stems)
    observed = {}
    original = stem_review.render_mix
    def render(*args, **kwargs):
        observed["render_thread"] = QThread.currentThread()
        result = original(*args, **kwargs)
        observed["result_type"] = type(result)
        return result
    monkeypatch.setattr(stem_review, "render_mix", render)
    window._run(lambda: stem_review.render_mix(source, window.project / "workspace" / "previews", use_cache=True),
                lambda result: observed.update(completion_thread=QThread.currentThread(), path=result.path), "preview")
    pump(application, lambda: window._worker_thread is None)
    assert observed["render_thread"] is not application.thread()
    assert observed["completion_thread"] is application.thread()
    assert observed["path"].is_file()
    window.close()

def test_default_selection_solo_mute_and_visual_state(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path, ("a", "b", "c"))); pump(application, lambda: window._worker_thread is None)
    ids = list(window.rows)
    assert set(window.audible_ids()) == set(ids) and not window.selected_ids
    window.rows[ids[0]].name_button.click(); assert window.selected_ids == {ids[0]} and window.audible_ids() == (ids[0],)
    window.rows[ids[1]].name_button.click(); assert set(window.audible_ids()) == {ids[0], ids[1]}
    assert window.rows[ids[0]].name_button.isChecked() and window.rows[ids[1]].name_button.isChecked()
    window.rows[ids[1]].solo_button.click(); assert window.audible_ids() == (ids[1],)
    window.rows[ids[1]].mute_button.click(); assert window.audible_ids() == () and window.selected_ids == {ids[0], ids[1]}
    window.clear_solos(); window.clear_mutes(); assert set(window.audible_ids()) == {ids[0], ids[1]}
    window.rows[ids[1]].name_button.click(); assert window.audible_ids() == (ids[0],)
    window.close()

def test_each_state_button_toggles_off_on_second_click(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path, ("a", "b"))); pump(application, lambda: window._worker_thread is None); window.show(); application.processEvents()
    first, second = list(window.rows.values())
    for button, model_value in (
        (first.name_button, lambda: first.stem_id in window.selected_ids),
        (first.solo_button, lambda: window.workspace._stem(first.stem_id).soloed),
        (first.mute_button, lambda: window.workspace._stem(first.stem_id).muted),
    ):
        assert not button.isChecked() and not model_value()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton); assert button.isChecked() and model_value()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton); assert not button.isChecked() and not model_value()
    first.name_button.click(); second.name_button.click(); first.name_button.click()
    assert window.selected_ids == {second.stem_id} and not first.name_button.isChecked() and second.name_button.isChecked()
    second.name_button.click()
    assert not window.selected_ids and set(window.audible_ids()) == set(window.rows)
    first.solo_button.click(); second.solo_button.click(); first.solo_button.click()
    assert not window.workspace._stem(first.stem_id).soloed and window.workspace._stem(second.stem_id).soloed
    underlying = window.audible_ids(); second.solo_button.click()
    assert not window.workspace._stem(second.stem_id).soloed and set(window.audible_ids()) == set(window.rows) and underlying == (second.stem_id,)
    first.mute_button.click(); second.mute_button.click(); first.mute_button.click()
    assert not window.workspace._stem(first.stem_id).muted and window.workspace._stem(second.stem_id).muted
    assert first.name_button.isChecked() is False and first.solo_button.isChecked() is False and first.mute_button.isChecked() is False
    window.clear_selection(); window.clear_solos(); window.clear_mutes()
    assert all(not row.name_button.isChecked() and not row.solo_button.isChecked() and not row.mute_button.isChecked() for row in window.rows.values())
    window.close()

def test_button_toggles_while_playing_preserve_playhead(application, tmp_path):
    factory = lambda paths, parent: StemMixTransport(paths, parent, sink_factory=FakeSink)
    window = StemReviewWindow(make_project(tmp_path, ("a", "b")), transport_factory=factory); pump(application, lambda: window._worker_thread is None)
    first = next(iter(window.rows.values())); window.transport.play_pause(); window.transport.sink.usecs = 25000; position = window.transport.position_ms
    first.name_button.click(); assert window.transport.position_ms == position
    first.name_button.click(); assert window.transport.position_ms == position
    first.solo_button.click(); first.solo_button.click(); first.mute_button.click(); first.mute_button.click()
    assert window.transport.position_ms == position and window.transport.is_playing
    window.transport.stop(); window.close()

def test_inline_rename_save_enter_escape_and_cancel(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path)); pump(application, lambda: window._worker_thread is None); row = next(iter(window.rows.values()))
    source = window.workspace.source_path(row.stem_id); original = source.read_bytes()
    row.begin_rename(); row.edit.setText("Electric Keys"); QTest.keyClick(row.edit, Qt.Key.Key_Return)
    assert window.workspace._stem(row.stem_id).display_label == "Electric Keys"
    row.begin_rename(); row.edit.setText("Discard Escape"); QTest.keyClick(row.edit, Qt.Key.Key_Escape); assert row.name_button.text() == "Electric Keys"
    row.begin_rename(); row.edit.setText("Discard X"); row.cancel_button.click(); assert row.name_button.text() == "Electric Keys"
    assert source.read_bytes() == original; window.close()

def test_inactive_rows_sort_last_and_are_dimmed(application, tmp_path):
    root = make_project(tmp_path, ("active", "quiet")); workspace = __import__("src.workspace", fromlist=["load_workspace"]).load_workspace(root)
    quiet = workspace._stem(next(s.id for s in workspace.stems if Path(s.source).stem == "quiet")); quiet.likely_inactive = True; quiet.measurements = {"rms_dbfs": -80, "peak_dbfs": -60, "active_fraction": 0}
    __import__("src.workspace", fromlist=["save_workspace"]).save_workspace(workspace)
    window = StemReviewWindow(root); pump(application, lambda: window._worker_thread is None)
    ordered = list(window.rows); assert Path(window.workspace._stem(ordered[-1]).source).stem == "quiet"
    assert window.rows[ordered[-1]].objectName() == "inactiveStemRow"; window.close()

def test_waveform_click_drag_shared_playhead(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path)); pump(application, lambda: window._worker_thread is None); window.show(); application.processEvents()
    waveform = window.combined_waveform; QTest.mouseClick(waveform, Qt.MouseButton.LeftButton, pos=waveform.rect().center())
    assert abs(window.transport.position_ms - window.transport.duration_ms // 2) < 20
    row = next(iter(window.rows.values())); QTest.mousePress(row.waveform, Qt.MouseButton.LeftButton, pos=row.waveform.rect().topLeft()+row.waveform.rect().center()/2); QTest.mouseMove(row.waveform, row.waveform.rect().center()); QTest.mouseRelease(row.waveform, Qt.MouseButton.LeftButton, pos=row.waveform.rect().center())
    assert row.waveform.position_ms == window.combined_waveform.position_ms
    window.close()

class FakeSink(QObject):
    def __init__(self, fmt, parent=None): super().__init__(parent); self.usecs = 0; self.started = self.suspended = False; self.buffer_size = 0
    def setBufferSize(self, value): self.buffer_size = value
    def bufferSize(self): return self.buffer_size
    def start(self, device): self.started = True; self.suspended = False
    def suspend(self): self.suspended = True
    def resume(self): self.suspended = False
    def stop(self): self.started = False; self.usecs = 0
    def processedUSecs(self): return self.usecs

def test_transport_play_pause_stop_seek_and_mix_switch_preserve_position(application, tmp_path):
    root = make_project(tmp_path); paths = {p.stem: p for p in (root/"stems").glob("*.wav")}; transport = StemMixTransport(paths, sink_factory=FakeSink)
    transport.play_pause(); transport.sink.usecs = 20000; before = transport.position_ms; transport.set_audible(("one",)); assert transport.position_ms == before and transport.is_playing
    transport.play_pause(); paused = transport.position_ms; assert not transport.is_playing and transport.sink.suspended
    transport.play_pause(); assert transport.is_playing and transport.position_ms == paused
    transport.seek_ms(30); assert abs(transport.position_ms-30) <= 1
    transport.stop(); assert transport.position_ms == 0 and not transport.is_playing; transport.close()

def test_waveform_envelope_and_cache(tmp_path):
    root = make_project(tmp_path, ("one",)); source = root/"stems"/"one.wav"; first, hit1 = extract_waveform(source, root/"workspace"/"waveforms", bins=32); second, hit2 = extract_waveform(source, root/"workspace"/"waveforms", bins=32)
    assert len(first.low) <= 32 and len(first.low) == len(first.high) and first.frames == second.frames
    assert not hit1 and hit2

def test_mix_device_irregular_byte_reads_match_offline_sum(tmp_path):
    root = tmp_path / "continuous"; root.mkdir(); frames = 10007; t = np.arange(frames) / 48000
    left = .12*np.sin(2*np.pi*317*t) + np.linspace(-.04,.04,frames)
    right = .09*np.sin(2*np.pi*613*t)
    stems = {
        "one": np.column_stack((left, right)),
        "two": np.column_stack((.07*np.sin(2*np.pi*997*t), .05*np.sin(2*np.pi*127*t))),
    }
    paths = {}
    for name,audio in stems.items():
        paths[name] = root/f"{name}.wav"; sf.write(paths[name], audio, 48000, subtype="FLOAT")
    decoded = {name: sf.read(path, dtype="float32", always_2d=True)[0] for name,path in paths.items()}
    device = StemMixDevice(paths); device.set_peaks({name: float(np.max(np.abs(audio))) for name,audio in decoded.items()})
    expected = (decoded["one"] + decoded["two"]) * device.safety_gain(tuple(paths))
    expected_bytes = expected.astype("<f4").tobytes(); sizes = (1,3,7,31,1001,2,9,4093,17,8,511); chunks=[]; index=0
    while sum(map(len,chunks)) < len(expected_bytes):
        chunks.append(device.readData(sizes[index % len(sizes)])); index += 1
    actual_bytes = b"".join(chunks)
    assert actual_bytes == expected_bytes
    actual = np.frombuffer(actual_bytes, dtype="<f4").reshape(-1,2)
    assert np.all(np.isfinite(actual)) and np.max(np.abs(actual)) <= .944060876 + 1e-7
    np.testing.assert_allclose(actual, expected, rtol=0, atol=0)
    np.testing.assert_allclose(np.diff(actual, axis=0), np.diff(expected, axis=0), rtol=0, atol=0)
    assert device.readData(1) == b"" and device.bytesAvailable() == 0
    device.close_sources()

def test_mix_device_unchanged_membership_has_no_block_boundary_artifacts(tmp_path):
    root = make_project(tmp_path, ("one", "two")); paths = {p.stem:p for p in (root/"stems").glob("*.wav")}; device = StemMixDevice(paths)
    decoded = [sf.read(path, dtype="float32", always_2d=True)[0] for path in paths.values()]; peaks = {name:float(np.max(np.abs(audio))) for name,audio in zip(paths,decoded)}; device.set_peaks(peaks)
    expected = sum(decoded) * device.safety_gain(tuple(paths)); chunks=[]
    for size in (1001,31,7,4095,3,8191)*20:
        chunk=device.readData(size)
        if not chunk: break
        chunks.append(chunk)
    while device.bytesAvailable(): chunks.append(device.readData(997))
    actual=np.frombuffer(b"".join(chunks),dtype="<f4").reshape(-1,2)
    np.testing.assert_array_equal(actual,expected)
    device.close_sources()

def test_transition_uses_short_click_protection_ramp(tmp_path):
    root=tmp_path/"ramp";root.mkdir();frames=2000;paths={}
    for name,value in (("positive",.5),("negative",-.5)):
        paths[name]=root/f"{name}.wav";sf.write(paths[name],np.full((frames,2),value,np.float32),48000,subtype="FLOAT")
    device=StemMixDevice(paths);device.set_peaks({"positive":.5,"negative":.5});device.set_audible(("positive",));device.readData(100*8)
    device.set_audible(("negative",));transition=np.frombuffer(device.readData(300*8),dtype="<f4").reshape(-1,2)[:,0]
    assert transition[0] > .49 and transition[239] < -.49
    assert np.max(np.abs(np.diff(transition[:240]))) < .01
    device.close_sources()

def test_int16_playback_conversion_is_clamped_and_interleaved(tmp_path):
    root=tmp_path/"int16";root.mkdir();path=root/"one.wav";audio=np.array([[1.2,-1.2],[.5,-.5],[0,0]],np.float32);sf.write(path,audio,48000,subtype="FLOAT")
    from PySide6.QtMultimedia import QAudioFormat
    device=StemMixDevice({"one":path},sample_format=QAudioFormat.SampleFormat.Int16);device.set_peaks({"one":1.0})
    values=np.frombuffer(device.readData(12),dtype="<i2").reshape(-1,2)
    assert values[0].tolist()==[32767,-32767] and values[2].tolist()==[0,0]
    device.close_sources()

def test_buffered_producer_stress_long_program_state_changes_and_seek(tmp_path):
    root=tmp_path/"stress";root.mkdir();rate=48000;frames=rate*30;t=np.arange(frames)/rate;paths={}
    for index,frequency in enumerate((173,431,997)):
        path=root/f"s{index}.wav";signal=(.08*np.sin(2*np.pi*frequency*t)).astype(np.float32);sf.write(path,np.column_stack((signal,signal)),rate,subtype="FLOAT");paths[f"s{index}"]=path
    device=StemMixDevice(paths,buffered=True);device.set_peaks({key:.08 for key in paths})
    def wait_for(count):
        deadline=time.monotonic()+2
        while time.monotonic()<deadline:
            with device._lock:
                if len(device._ring)>=count:return
            time.sleep(.001)
        raise AssertionError("producer did not fill playback buffer")
    total=0
    for index in range(700):
        size=(1001,4096,7777,31)[index%4];wait_for(size);chunk=device.readData(size);assert len(chunk)==size;total+=len(chunk)
        if index%100==25:device.set_audible(("s0",))
        elif index%100==50:device.set_audible(("s0","s2"))
        elif index%100==75:device.set_audible(tuple(paths))
    device.seek_frame(rate*10);wait_for(8192);assert len(device.readData(8192))==8192
    assert total>2_000_000 and device.underrun_count==0 and device.max_read_seconds<.05 and device.max_render_seconds<.1
    assert device.frame_position>=rate*10 and device.read_calls==701
    device.close_sources()

def test_open_existing_has_no_cross_thread_parent_warning_and_reopens(application, tmp_path, monkeypatch):
    output = tmp_path / "output"; root = make_project(output)
    input_path = tmp_path / "song.wav"; input_path.write_bytes(b"selected project identity")
    # make_project(output) creates output/song, matching safe_project_name(song.wav).
    monkeypatch.setattr("src.config.OUTPUT_DIR", output)
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    main = MainWindow(show_dialogs=False); main.file_picker.set_path(input_path)
    try:
        main.open_existing_stem_review(); first = main.review_window
        pump(application, lambda: first._worker_thread is None)
        assert first.isVisible() and not any("different thread" in message for message in messages)
        first.close(); pump(application, lambda: not first.isVisible())
        main.open_existing_stem_review(); second = main.review_window
        pump(application, lambda: second._worker_thread is None)
        assert second is not first and second.isVisible()
        assert not any("QObject::setParent" in message for message in messages)
        second.close(); pump(application, lambda: not second.isVisible())
    finally:
        qInstallMessageHandler(previous); main.close()

def test_close_during_worker_finishes_then_closes_cleanly(application, tmp_path):
    window = StemReviewWindow(make_project(tmp_path)); pump(application, lambda: window._worker_thread is None)
    window._run(lambda: 1, lambda result: None, "operation")
    window.close()
    assert window._close_when_finished
    pump(application, lambda: window._worker_thread is None and not window.isVisible())
    assert window._worker is None

def test_worker_success_and_failure():
    success, failure = [], []
    worker = ReviewWorker(lambda: 42); worker.completed.connect(success.append); worker.run(); assert success == [42]
    worker = ReviewWorker(lambda: (_ for _ in ()).throw(RuntimeError("broken"))); worker.failed.connect(lambda message, details: failure.append((message, details))); worker.run()
    assert failure[0][0] == "broken" and "RuntimeError" in failure[0][1]

def test_export_filename_sanitization():
    assert safe_export_label('Synth: Pads / Lead?') == "Synth_ Pads _ Lead_"
