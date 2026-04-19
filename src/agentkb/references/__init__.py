"""Refs store: automated mirrors of external prose, indexed via the wiki.

Refs live under ``<wiki>/sources/refs/<id>/`` and share the wiki's
``wiki:source`` collection tag. They're searchable via ``-s wiki`` or
the narrower ``-s wiki:source``.
"""

from __future__ import annotations

from pathlib import Path

from agentkb.output import echo_status
from agentkb.references import manifest as manifest_mod
from agentkb.references.fetchers import fetch
from agentkb.references.manifest import Ref, mark_synced, refs_root


def add(url: str, *, ref_id: str | None = None, kind: str | None = None,
        subpath: str | None = None, refresh: str | None = None) -> Ref:
    """Add a ref to the manifest (does NOT fetch). Returns the stored Ref."""
    refs = manifest_mod.load()
    kind = kind or manifest_mod.infer_kind(url)
    rid = ref_id or manifest_mod.infer_id(url, kind)
    if manifest_mod.find(refs, rid):
        raise ValueError(f"ref with id {rid!r} already exists")

    ref = Ref(
        id=rid,
        kind=kind,
        source=url,
        subpath=subpath,
        refresh=refresh or ("never" if kind == "url" else "pull"),
    )
    refs.append(ref)
    manifest_mod.save(refs)
    return ref


def remove(ref_id: str) -> bool:
    """Remove a ref from the manifest and delete its local content."""
    refs = manifest_mod.load()
    target = manifest_mod.find(refs, ref_id)
    if target is None:
        return False
    refs = [r for r in refs if r.id != ref_id]
    manifest_mod.save(refs)

    import shutil
    dest = refs_root() / ref_id
    if dest.exists():
        shutil.rmtree(dest)
    return True


def sync(ref_id: str | None = None, *, json_output: bool = False) -> dict:
    """Run fetchers for one ref (or all). Returns per-id status."""
    refs = manifest_mod.load()
    if ref_id is not None:
        target = manifest_mod.find(refs, ref_id)
        if target is None:
            return {"error": f"no ref with id {ref_id!r}"}
        to_sync = [target]
    else:
        to_sync = [r for r in refs if r.refresh != "never" or not (refs_root() / r.id).exists()]

    results: dict[str, str] = {}
    for ref in to_sync:
        dest = refs_root() / ref.id
        echo_status(f"[agentkb] refs: syncing {ref.id} ({ref.kind})", json_output=json_output)
        try:
            commit = fetch(ref, dest)
            mark_synced(ref, commit=commit)
            results[ref.id] = commit or "ok"
        except Exception as e:
            results[ref.id] = f"error: {e}"

    manifest_mod.save(refs)
    return results


def list_refs() -> list[Ref]:
    return manifest_mod.load()
