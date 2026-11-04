import hashlib
import json
import os
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.workspace import (discover_workspace, load_workspace, measure_activity,
                           render_mix, save_workspace)

RATE = 48000

def wav(path, amplitude=.1, seconds=.1, frequency=220):
    path.parent.mkdir(parents=True, exist_ok=True)
    t = np.arange(int(RATE * seconds)) / RATE
    signal = amplitude * np.sin(2 * np.pi * frequency * t)
    sf.write(path, np.column_stack((signal, signal)), RATE, subtype="PCM_24")
    return path

def project(tmp_path, names):
    root = tmp_path / "output" / "song"
    for index, name in enumerate(names): wav(root / "stems" / f"{name}.wav", frequency=220 + index * 20)
    return root

@pytest.mark.parametrize("names", [("vocals", "instrumental"), ("vocals", "drums", "bass", "guitar", "piano", "other"), ("organ", "future_texture", "brass")])
def test_dynamic_arbitrary_workspace_loading(tmp_path, names):
    workspace = discover_workspace(project(tmp_path, names))
    assert [Path(item.source).stem for item in workspace.stems] == sorted(names)

def test_rename_persistence_is_atomic_and_never_renames_source(tmp_path, monkeypatch):
    root = project(tmp_path, ("other",)); source = root / "stems" / "other.wav"; digest = hashlib.sha256(source.read_bytes()).hexdigest()
    workspace = discover_workspace(root); workspace.rename_stem(workspace.stems[0].id, "Synth Pads")
    replaced = []; original = os.replace
    monkeypatch.setattr("src.workspace.model.os.replace", lambda a, b: (replaced.append((a, b)), original(a, b))[1])
    save_workspace(workspace); loaded = load_workspace(root)
    assert replaced and loaded.stems[0].display_label == "Synth Pads"
    assert source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == digest

def test_missing_malformed_and_stale_metadata_recovers(tmp_path):
    root = project(tmp_path, ("one", "two")); assert len(load_workspace(root).stems) == 2
    path = root / "workspace" / "stem_workspace.json"; path.parent.mkdir(); path.write_text("not json")
    assert len(load_workspace(root).stems) == 2
    path.write_text(json.dumps({"schema_version": 1, "stems": [{"source": "stems/missing.wav", "display_label": "Missing"}], "groups": []}))
    assert [s.display_label for s in load_workspace(root).stems] == ["One", "Two"]

def test_activity_heuristic_is_advisory_and_never_deletes(tmp_path):
    root = project(tmp_path, ("quiet",)); source = root / "stems" / "quiet.wav"; wav(source, amplitude=0)
    result = measure_activity(source)
    assert result.likely_inactive and result.active_fraction == 0
    assert source.is_file()

def test_solo_mute_multiple_and_clear_logic(tmp_path):
    workspace = discover_workspace(project(tmp_path, ("a", "b", "c"))); a, b, c = workspace.stems
    b.muted = True; assert workspace.audible_ids() == (a.id, c.id)
    a.soloed = c.soloed = True; assert workspace.audible_ids() == (a.id, c.id)
    a.muted = True; assert workspace.audible_ids() == (c.id,)
    workspace.clear_solos(); workspace.clear_mutes(); assert workspace.audible_ids() == (a.id, b.id, c.id)

def test_selection_and_solo_override_rules(tmp_path):
    workspace = discover_workspace(project(tmp_path, ("a", "b", "c"))); a, b, c = workspace.stems
    assert workspace.audible_ids(()) == (a.id, b.id, c.id)
    assert workspace.audible_ids((a.id,)) == (a.id,)
    assert workspace.audible_ids((a.id, b.id)) == (a.id, b.id)
    b.soloed = True; assert workspace.audible_ids((a.id, c.id)) == (b.id,)
    b.muted = True; assert workspace.audible_ids((a.id, c.id)) == ()
    workspace.clear_solos(); workspace.clear_mutes(); assert workspace.audible_ids((a.id, c.id)) == (a.id, c.id)

def test_group_create_rename_membership_and_dissolve(tmp_path):
    workspace = discover_workspace(project(tmp_path, ("a", "b", "c"))); ids = [s.id for s in workspace.stems]
    group = workspace.create_group("Keys", ids[:2]); workspace.rename_group(group.id, "Layers"); workspace.set_group_members(group.id, ids[1:])
    assert group.display_label == "Layers" and group.members == ids[1:]
    workspace.dissolve_group(group.id); assert not workspace.groups and len(workspace.stems) == 3

def test_group_audio_alignment_clipping_protection_cache_and_immutability(tmp_path):
    root = project(tmp_path, ("a", "b")); paths = tuple((root / "stems").glob("*.wav"))
    wav(paths[0], .8); wav(paths[1], .8); before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
    result = render_mix(paths, root / "workspace" / "previews", use_cache=True)
    audio, rate = sf.read(result.path, always_2d=True)
    assert rate == RATE and len(audio) == int(RATE * .1) and np.max(np.abs(audio)) <= 10 ** (-.5 / 20) + 1e-5
    assert result.attenuation_db < 0 and render_mix(paths, root / "workspace" / "previews", use_cache=True).cache_hit
    assert before == [hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]

def test_seek_state_and_source_switch_persist_independently(tmp_path):
    root = project(tmp_path, ("a",)); separated = discover_workspace(root); separated.position_ms = 135000; save_workspace(separated)
    wav(root / "restored" / "a_restored.wav"); restored = discover_workspace(root, "restored"); restored.position_ms = 5000; save_workspace(restored)
    assert load_workspace(root, "restored").position_ms == 5000
    assert load_workspace(root, "separated").position_ms == 135000
