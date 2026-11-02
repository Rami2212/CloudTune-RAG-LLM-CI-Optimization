"""Resolve and freeze OpenRouter generation settings from the environment.

The configuration JSON selects the repository, arms and frozen corpus, but is
not an authority for the generator model or token ceiling. These two values
come exclusively from OPENROUTER_MODEL and OPENROUTER_MAX_TOKENS (loaded by the
entrypoint from .env with exported environment variables taking precedence).
The returned config is a new object; existing configuration is not mutated.
"""
from __future__ import annotations

import os
import re


def resolve_openrouter_env(config: dict) -> dict:
    """Validate env-only LLM settings and snapshot them for reproducible runs."""
    model = os.environ.get("OPENROUTER_MODEL", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_./:-]+:free", model):
        raise ValueError("Set OPENROUTER_MODEL to a specific OpenRouter :free model in .env")

    raw_max_tokens = os.environ.get("OPENROUTER_MAX_TOKENS", "").strip()
    if not re.fullmatch(r"[0-9]+", raw_max_tokens):
        raise ValueError("Set OPENROUTER_MAX_TOKENS to an integer from 256 to 48000 in .env")
    max_tokens = int(raw_max_tokens)
    if not 256 <= max_tokens <= 48000:
        raise ValueError("OPENROUTER_MAX_TOKENS must be between 256 and 48000")

    resolved = dict(config)
    rag = dict(config.get("rag", {}))
    # Override even if an old experiment template still contains a different
    # generator_model/max_tokens pair. Do not allow silent JSON fallback.
    rag["generator_model"] = model
    rag["max_tokens"] = max_tokens
    resolved["rag"] = rag
    return resolved
