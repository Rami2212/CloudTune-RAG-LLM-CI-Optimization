"""Offline, source-bound setup-node npm-cache compatibility policy.

The registry is a frozen snapshot of official release refs, not a promise
that an arbitrary SHA or a future major release supports this cache contract.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("setup_node_releases.json")
REGISTRY = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
SUPPORTED_MAJORS = frozenset({4, 5, 6, 7})


def _release_refs() -> dict[str, str]:
    if (REGISTRY.get("schema") != 1 or REGISTRY.get("repository") != "actions/setup-node"
            or set(REGISTRY.get("supported_majors", [])) != SUPPORTED_MAJORS):
        raise ValueError("Invalid setup-node release registry")
    refs = REGISTRY.get("refs")
    if not isinstance(refs, dict) or not refs:
        raise ValueError("Empty setup-node release registry")
    for tag, sha in refs.items():
        match = re.fullmatch(r"v(\d+)(?:\.\d+(?:\.\d+)?)?", tag)
        if (not match or int(match[1]) not in SUPPORTED_MAJORS
                or not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha)):
            raise ValueError("Invalid setup-node release entry")
    return refs


RELEASE_REFS = _release_refs()


def compatible_setup_node_refs() -> frozenset[str]:
    """Used by Python admission and embedded into the compiled TS generator."""
    return frozenset("actions/setup-node@" + ref
                     for ref in (*RELEASE_REFS, *RELEASE_REFS.values()))


def setup_node_cache_compatibility(reference: object) -> dict:
    if not isinstance(reference, str) or not reference.startswith("actions/setup-node@"):
        return {"supported": False, "reason": "NOT_OFFICIAL_SETUP_NODE_REF"}
    ref = reference.removeprefix("actions/setup-node@")
    sha = RELEASE_REFS.get(ref)
    if sha is None and re.fullmatch(r"[a-f0-9]{40}", ref):
        sha = ref if ref in RELEASE_REFS.values() else None
    if sha is None:
        return {"supported": False, "reason": "UNREVIEWED_SETUP_NODE_REF"}
    return {"supported": True, "reason": None, "commit_sha": sha,
            "release_tags": sorted(tag for tag, commit in RELEASE_REFS.items() if commit == sha)}


def compatibility_digest() -> str:
    return hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()
