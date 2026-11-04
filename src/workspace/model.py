"""Persistent project-relative organization layered over immutable stem WAVs."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1


class WorkspaceError(RuntimeError):
    pass


@dataclass
class StemRecord:
    id: str
    source: str
    display_label: str
    muted: bool = False
    soloed: bool = False
    likely_inactive: bool = False
    measurements: dict[str, float] = field(default_factory=dict)


@dataclass
class StemGroup:
    id: str
    display_label: str
    members: list[str]


@dataclass
class StemWorkspace:
    project: Path
    source_kind: str
    stems: list[StemRecord]
    groups: list[StemGroup] = field(default_factory=list)
    position_ms: int = 0

    @property
    def metadata_path(self) -> Path:
        name = "stem_workspace.json" if self.source_kind == "separated" else f"stem_workspace_{self.source_kind}.json"
        return self.project / "workspace" / name

    def audible_ids(self, selected: tuple[str, ...] = ()) -> tuple[str, ...]:
        if any(stem.soloed for stem in self.stems):
            return tuple(stem.id for stem in self.stems if stem.soloed and not stem.muted)
        selected_set = set(selected)
        return tuple(stem.id for stem in self.stems
                     if not stem.muted and (not selected_set or stem.id in selected_set))

    def clear_solos(self) -> None:
        for stem in self.stems: stem.soloed = False

    def clear_mutes(self) -> None:
        for stem in self.stems: stem.muted = False

    def rename_stem(self, stem_id: str, label: str) -> None:
        label = label.strip()
        if not label: raise WorkspaceError("A display label cannot be empty.")
        self._stem(stem_id).display_label = label

    def create_group(self, label: str, members: list[str]) -> StemGroup:
        valid = list(dict.fromkeys(members))
        if len(valid) < 2 or any(not any(s.id == item for s in self.stems) for item in valid):
            raise WorkspaceError("A group requires at least two existing stems.")
        group = StemGroup(uuid.uuid4().hex, label.strip() or "Group", valid)
        self.groups.append(group)
        return group

    def rename_group(self, group_id: str, label: str) -> None:
        label = label.strip()
        if not label: raise WorkspaceError("A group label cannot be empty.")
        self._group(group_id).display_label = label

    def dissolve_group(self, group_id: str) -> None:
        self.groups.remove(self._group(group_id))

    def set_group_members(self, group_id: str, members: list[str]) -> None:
        group = self._group(group_id)
        valid = list(dict.fromkeys(members))
        if len(valid) < 2: raise WorkspaceError("A group requires at least two stems.")
        if any(not any(s.id == item for s in self.stems) for item in valid):
            raise WorkspaceError("A group member is no longer available.")
        group.members = valid

    def _stem(self, value: str) -> StemRecord:
        try: return next(item for item in self.stems if item.id == value)
        except StopIteration as exc: raise WorkspaceError(f"Unknown stem: {value}") from exc

    def _group(self, value: str) -> StemGroup:
        try: return next(item for item in self.groups if item.id == value)
        except StopIteration as exc: raise WorkspaceError(f"Unknown group: {value}") from exc

    def source_path(self, stem_id: str) -> Path:
        path = (self.project / self._stem(stem_id).source).resolve()
        if self.project.resolve() not in path.parents:
            raise WorkspaceError("Workspace source escapes the project directory.")
        return path


def _source_files(project: Path, source_kind: str) -> dict[str, Path]:
    if source_kind == "restored":
        return {p.stem.removesuffix("_restored"): p for p in sorted((project / "restored").glob("*_restored.wav"))}
    return {p.stem: p for p in sorted((project / "stems").glob("*.wav"))}


def discover_workspace(project: Path, source_kind: str = "separated") -> StemWorkspace:
    project = Path(project).resolve()
    files = _source_files(project, source_kind)
    stems = [StemRecord(uuid.uuid5(uuid.NAMESPACE_URL, f"{source_kind}:{name}").hex,
                        path.relative_to(project).as_posix(), name.replace("_", " ").title())
             for name, path in files.items()]
    return StemWorkspace(project, source_kind, stems)


def load_workspace(project: Path, source_kind: str = "separated") -> StemWorkspace:
    fresh = discover_workspace(project, source_kind)
    path = fresh.metadata_path
    if not path.is_file(): return fresh
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != SCHEMA_VERSION: return fresh
        saved = {item["source"]: item for item in data.get("stems", [])}
        for stem in fresh.stems:
            item = saved.get(stem.source, {})
            stem.display_label = str(item.get("display_label", stem.display_label))
            stem.muted, stem.soloed = bool(item.get("muted")), bool(item.get("soloed"))
            stem.likely_inactive = bool(item.get("likely_inactive"))
            stem.measurements = {str(k): float(v) for k, v in item.get("measurements", {}).items()}
        ids = {s.id for s in fresh.stems}
        fresh.groups = [StemGroup(str(g["id"]), str(g["display_label"]), list(g["members"]))
                        for g in data.get("groups", []) if len(set(g.get("members", [])) & ids) >= 2]
        for group in fresh.groups: group.members = [item for item in group.members if item in ids]
        fresh.position_ms = max(0, int(data.get("position_ms", 0)))
        return fresh
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return fresh


def save_workspace(workspace: StemWorkspace) -> Path:
    path = workspace.metadata_path
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": SCHEMA_VERSION, "source": workspace.source_kind,
               "position_ms": workspace.position_ms,
               "stems": [vars(item) for item in workspace.stems],
               "groups": [vars(item) for item in workspace.groups]}
    handle, temporary = tempfile.mkstemp(prefix=".stem-workspace-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise
    return path
