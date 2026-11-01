"""Aides communes aux routes."""
from pathlib import Path

from fastapi import HTTPException

from .. import config
from ..project import Project


def proj(name) -> Project:
    base = Path(config.load()["astro_root"])
    if not name or any(c in name for c in '/\\:') or name in (".", "..") or name.startswith("."):
        raise HTTPException(404, f"projet introuvable : {name}")
    root = base / name
    if root.resolve().parent != base.resolve() or not (root / "project.json").exists():
        raise HTTPException(404, f"projet introuvable : {name}")
    return Project.load(root)
