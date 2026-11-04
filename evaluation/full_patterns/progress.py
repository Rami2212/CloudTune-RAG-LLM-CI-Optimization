"""Flushed operational diagnostics; never include credentials or model payloads."""
from __future__ import annotations

from datetime import datetime, timezone
import os
import re

from scripts.experiment_environment import redact


def _normal_message(stage: str, message: str) -> str | None:
    """Keep decisions and stage summaries; detailed diagnostics remain opt-in."""
    if stage == "VERIFY":
        return None
    if stage == "DEVICE" and message.startswith("Checking configured"):
        return None
    if stage == "CONTEXT" and (" archived " in message or "reading pinned tree" in message):
        return None
    if stage == "HISTORY" and (message.startswith("Reading jobs") or message.startswith("[") or "source cutoff=" in message):
        return None
    if stage == "PATTERN":
        return None  # All dispositions are already counted in APPLICABILITY.
    if stage == "VALIDATION" and re.search(r"verdict=(NO_CHANGE|MISSING_EVIDENCE)(?:;|$)", message):
        return None
    if stage == "EMBEDDING" and "model ready" in message:
        return None
    if stage == "PREP":
        if "screening eligibility" in message:
            return None
        message=message.split("; snapshot=",1)[0]
        message=re.sub(r"commit=([a-f0-9]{12})[a-f0-9]+",r"commit=\1",message)
    if stage == "PROPOSAL":
        message="; ".join(message.split("; ")[:3])
    if stage == "RAG" and message.startswith("Completed"):
        message=message.split("; report=",1)[0]
    if stage == "CONTEXT" and message.startswith("Collection complete:"):
        message=message.split("; bytes=",1)[0]
    return message


def progress(stage: str, message: str) -> None:
    message=redact(str(message))
    for name in ("SUPABASE_SECRET_KEY","SUPABASE_SERVICE_ROLE_KEY","CLOUDTUNE_FORK_TOKEN"):
        value=os.environ.get(name)
        if value:message=message.replace(value,"[REDACTED]")
    message=re.sub(r"https?://[^\s/@]+:[^\s/@]+@","https://[REDACTED]@",message)
    message=" ".join(message.splitlines())
    message=re.sub(r"[\x00-\x08\x0b-\x1f\x7f]","",message)
    if os.environ.get("CLOUDTUNE_LOG_LEVEL","info").strip().lower() not in {"debug","verbose"}:
        message=_normal_message(stage,message)
        if message is None:
            return
    now=datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
    print(f"[{now}] [{stage}] {message}",flush=True)
