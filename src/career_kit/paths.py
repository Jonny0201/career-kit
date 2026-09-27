"""Workspace boundaries. Never borrow an enclosing repository's data/config."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .errors import ContractError


def discover_project_root(start=None):
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        marker = directory / ".career-kit.json"
        if marker.is_file() and not marker.is_symlink():
            try:
                value = json.loads(marker.read_text())
            except (OSError, ValueError):
                raise ContractError("WORKSPACE_INVALID", "workspace marker is invalid")
            if value != {"project": "career-kit", "format_version": 1}:
                raise ContractError("WORKSPACE_INVALID", "unsupported workspace marker")
            return directory
        # A missing marker in this checkout must never fall through to its parent.
        if (directory / ".git").exists() or (directory / "pyproject.toml").exists():
            break
    raise ContractError("WORKSPACE_NOT_FOUND", "run from an initialized Career Kit checkout; ancestor workspaces are not a fallback")


@dataclass(frozen=True)
class ProjectPaths:
    root: Path

    @classmethod
    def discover(cls, start=None):
        return cls(discover_project_root(start))

    def path(self, relative):
        value = Path(relative)
        if value.is_absolute() or ".." in value.parts or not value.parts:
            raise ContractError("PATH_INVALID", "use a nonempty workspace-relative path without traversal")
        cursor = self.root
        for part in value.parts:
            cursor /= part
            if cursor.is_symlink():
                raise ContractError("PATH_INVALID", "symbolic links are not workspace inputs")
        target = cursor.resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ContractError("PATH_INVALID", "path escapes workspace")
        return target

    def permanent(self, relative):
        target = self.path(relative)
        if target.is_relative_to(self.runtime):
            raise ContractError("PATH_INVALID", "permanent records cannot be placed in runtime")
        return target

    @property
    def runtime(self):
        return self.path("runtime.nosync")

    def runtime_path(self, relative="."):
        return self.path(Path("runtime.nosync") / relative)

    def initialize_runtime(self):
        for name in ("work", "cache", "locks", "tmp-scripts"):
            self.runtime_path(name).mkdir(parents=True, exist_ok=True)
