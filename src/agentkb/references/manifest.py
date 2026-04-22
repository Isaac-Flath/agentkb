"""Refs manifest: JSON registry of mirrored external prose.

Lives at ``<wiki>/sources/refs/manifest.json`` so it travels with the wiki
git remote alongside the content it manages.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from agentkb.config import paths


@dataclass
class Ref:
    id: str
    kind: str                    # "git" | "url" (phase 1)
    source: str
    subpath: str | None = None
    refresh: str = "pull"        # "pull" | "never"
    last_synced: str | None = None
    last_commit: str | None = None


def refs_root() -> Path:
    """Directory where manifest-managed refs live (under the wiki's sources/)."""
    return paths.wiki_dir() / "sources" / "refs"


def manifest_path() -> Path:
    return refs_root() / "manifest.json"


def load() -> list[Ref]:
    p = manifest_path()
    if not p.exists():
        return []
    raw = json.loads(p.read_text())
    return [Ref(**entry) for entry in raw.get("refs", [])]


def save(refs: list[Ref]) -> None:
    p = manifest_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"refs": [{k: v for k, v in asdict(r).items() if v is not None} for r in refs]}
    p.write_text(json.dumps(payload, indent=2) + "\n")


def find(refs: list[Ref], ref_id: str) -> Ref | None:
    for r in refs:
        if r.id == ref_id:
            return r
    return None


def mark_synced(ref: Ref, *, commit: str | None = None) -> None:
    ref.last_synced = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if commit is not None:
        ref.last_commit = commit


def infer_kind(url: str) -> str:
    """Infer fetcher kind from a URL. Phase 1: git or url."""
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = parsed.path.lower()
    if host == "github.com" and path.count("/") >= 2:
        return "git"
    if path.endswith(".git"):
        return "git"
    return "url"


def infer_id(url: str, kind: str) -> str:
    """Pick a default slug for an id based on URL shape."""
    parsed = urlparse(url)
    if kind == "git":
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1].removesuffix(".git")
            return slugify(f"{owner}-{repo}")
    # url: host + last path segment
    tail = [p for p in parsed.path.split("/") if p]
    base = parsed.netloc.replace(".", "-") if parsed.netloc else "ref"
    if tail:
        base = f"{base}-{tail[-1]}"
    return slugify(base)


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return text or "ref"
