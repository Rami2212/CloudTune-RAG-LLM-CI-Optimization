"""Phase 3 verification: read-only index checks and opt-in free-model smoke.

Local, remote and retrieve modes only read frozen data. Explicit smoke mode
sends a synthetic CI fixture to the pinned free generator. No mode creates
forks, dispatches GitHub Actions, uploads embeddings, or changes RAG records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from pathlib import Path

from scripts.experiment_environment import load_env
from evaluation.rag_retriever import Retriever
from evaluation.optimizers.rag_llm import generate_rag_candidate
from evaluation.candidate_validator import validate_candidate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "evaluation/configs/fork_pilot.json"
CORPUS = ROOT / "research-data/rag/rag_dataset.jsonl"


def check_local(config: dict, *, corpus: Path = CORPUS) -> dict:
    rag = config.get("rag", {})
    model = rag.get("generator_model")
    max_tokens = rag.get("max_tokens")
    expected = rag.get("dataset_sha256")
    if (not isinstance(model, str) or not model.endswith(":free") or
            not isinstance(max_tokens, int) or max_tokens < 1):
        raise ValueError("Phase 3 requires an explicitly pinned free model and positive max_tokens")
    if rag.get("embedding_model") != "BAAI/bge-m3":
        raise ValueError("Phase 3 requires frozen BAAI/bge-m3 embeddings")
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("Phase 3 requires the frozen dataset SHA256")
    observed = hashlib.sha256(corpus.read_bytes()).hexdigest()
    if observed != expected:
        raise ValueError("Local RAG corpus differs from the frozen evaluation SHA256")
    revision = rag.get("embedding_revision")
    if revision != "AUTO_PIN_SINGLE" and (
        not isinstance(revision, str) or len(revision) != 40 or
        any(ch not in "0123456789abcdef" for ch in revision)
    ):
        raise ValueError("Phase 3 embedding revision must be frozen or AUTO_PIN_SINGLE")
    if not isinstance(rag.get("top_k"), int) or not 1 <= rag["top_k"] <= 20:
        raise ValueError("Phase 3 top_k must be between 1 and 20")
    return {"status": "LOCAL_CORPUS_VERIFIED", "dataset_sha256": observed,
            "embedding_model": rag["embedding_model"], "embedding_revision": revision,
            "generator_model": model, "max_tokens": max_tokens,
            "top_k": rag["top_k"], "network_requests": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--mode", choices=("local", "remote", "retrieve", "smoke"), default="local",
                        help="local/remote/retrieve: read-only verification; smoke: explicitly call free OpenRouter with a synthetic CI fixture")
    parser.add_argument("--query", default="GitHub Actions dependency-download caching with lockfile invalidation")
    options = parser.parse_args()
    try:
        config_path = options.config if options.config.is_absolute() else ROOT / options.config
        config = json.loads(config_path.read_text(encoding="utf-8"))
        summary = check_local(config, corpus=CORPUS)
        if options.mode != "local":
            load_env(ROOT / ".env")
            revision = config["rag"]["embedding_revision"]
            retriever = Retriever(revision=None if revision == "AUTO_PIN_SINGLE" else revision,
                                  dataset_path=CORPUS, dataset_sha256=config["rag"]["dataset_sha256"])
            summary.update(status="REMOTE_CORPUS_VERIFIED",
                           embedding_revision=retriever.revision,
                           document_count=retriever.identity["document_count"])
            if options.mode == "retrieve":
                chunks = retriever.retrieve(options.query, top_k=config["rag"]["top_k"])
                summary["status"] = "RAG_RETRIEVAL_VERIFIED"
                # Do not print the full indexed documents or credentials.
                summary["retrieval"] = [
                    {"document_id": c["document_id"], "pattern_id": c["pattern_id"],
                     "chunk_index": c["chunk_index"], "similarity": c["similarity"]}
                    for c in chunks
                ]
            if options.mode == "smoke":
                # A development-only end-to-end smoke probe, never a held-out
                # repository or a measured CI run. No forks or Actions dispatch.
                with tempfile.TemporaryDirectory(prefix="cloudtune-phase3-smoke-") as folder:
                    snapshot = Path(folder)
                    (snapshot / "source").mkdir()
                    original = ("name: CloudTune synthetic Phase 3 smoke\n"
                                "on:\n  workflow_dispatch:\njobs:\n  test:\n"
                                "    runs-on: ubuntu-latest\n    steps:\n"
                                "      - uses: actions/checkout@v4\n"
                                "      - uses: actions/setup-node@v4\n"
                                "        with:\n          node-version: '22'\n"
                                "      - run: npm ci\n      - run: npm test\n").encode()
                    (snapshot / "source/original.yml").write_bytes(original)
                    (snapshot / "manifest.json").write_text(json.dumps({
                        "workflow_sha256": hashlib.sha256(original).hexdigest(),
                        "workflow_path": ".github/workflows/ci.yml",
                        "source_commit_sha": "0" * 40,
                        "required_checks": {"status": "synthetic_smoke_only"},
                        "ci_history": {"status": "not_collected"}}))
                    candidate = generate_rag_candidate(snapshot, retriever=retriever,
                        model=config["rag"]["generator_model"],
                        top_k=config["rag"]["top_k"],
                        max_tokens=config["rag"]["max_tokens"])
                    verdict = (validate_candidate(original, (snapshot / "candidates/C/optimized.yml").read_bytes())
                               if candidate["decision"] == "APPLY" else
                               {"verdict": "NO_CHANGE", "reasons": []})
                    summary.update(status="FREE_MODEL_SMOKE_COMPLETED",
                                   decision=candidate["decision"],
                                   safety_verdict=verdict["verdict"],
                                   validation_reasons=verdict.get("reasons", []),
                                   prompt_sha256=candidate["prompt_sha256"],
                                   model=candidate["model"],
                                   generated_on="synthetic_non_held_out_fixture",
                                   github_actions_runs=0)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, json.JSONDecodeError) as error:
        # Do not include server response bodies or credential values in reports.
        print("Phase 3 verification failed: " + type(error).__name__ + ": " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
