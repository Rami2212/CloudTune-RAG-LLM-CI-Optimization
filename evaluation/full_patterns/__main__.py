"""Full-pattern study commands; explicit batch --run can dispatch admitted CI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from scripts.experiment_environment import load_env
from evaluation.repository_preparation import GitHubReader, write_json_immutable
from .context import build_context, collect_context
from .registry import DATASET, ROOT, load_registry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    catalogue = sub.add_parser("catalogue", help="Audit all eligible corpus patterns, offline")
    catalogue.add_argument("--output", type=Path)
    verify = sub.add_parser("verify", help="Run all 25 controlled development scenarios, no repository set or CI")
    verify.add_argument("--output", type=Path, default=ROOT/"evaluation/full-pattern-results/development-verification.json")
    sub.add_parser("device", help="Check and record actual embedding device availability")
    smoke=sub.add_parser("smoke",help="Real free-model and retrieval test on synthetic inputs, no GitHub writes")
    smoke.add_argument("--output",type=Path,required=True)
    smoke.add_argument("--model",help="Defaults to the user's pinned OPENROUTER_MODEL")
    batch = sub.add_parser("batch", add_help=False, help="Full-pattern member batch (use batch --help)")
    batch.add_argument("batch_args", nargs=argparse.REMAINDER)
    for command in ("context", "collect", "propose", "validate"):
        p = sub.add_parser(command)
        p.add_argument("--output", type=Path, required=True, help="Separate full-pattern output directory")
        if command != "validate":
            p.add_argument("--snapshot", type=Path, required=True, help="Pinned repository snapshot containing manifest.json")
        if command in {"context", "propose"}:
            p.add_argument("--extended", type=Path, help="Pinned extended context collected by the collect command")
            p.add_argument("--context-chars", type=int, default=48000)
        if command == "propose":
            p.add_argument("--model", required=True, help="Pinned OpenRouter :free model; never silently changed")
            p.add_argument("--top-k", type=int, default=3, help="Chunks per applicable pattern, not a global pattern limit")
            p.add_argument("--max-tokens", type=int, default=24000)
            p.add_argument("--embedding-revision", help="Optional pinned BGE-M3 revision; otherwise audits a single indexed revision")
        if command == "validate":
            p.add_argument("--reviews", type=Path, help="Review files named PATTERN-ID.json with hashed evidence alongside")
            p.add_argument("--arm", choices=("B", "C", "D"), default="C")
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        from .batch import main as batch_main
        return batch_main(sys.argv[2:])
    args = parser.parse_args()
    try:
        registry = load_registry(DATASET)
        if args.command == "verify":
            from .batch import verify_development
            verified=verify_development(registry,args.output)
            print(json.dumps({"passed":verified["passed"],"patterns":len(verified["checks"]),"scope":verified["scope"]},indent=2))
            return 0 if verified["passed"] else 1
        if args.command == "device":
            from .device import inspect_device
            load_env(ROOT/".env")
            print(json.dumps(inspect_device(),indent=2))
            return 0
        if args.command == "smoke":
            import os
            from .smoke import run_smoke
            load_env(ROOT/".env")
            result=run_smoke(args.output,registry=registry,model=args.model or os.environ.get("OPENROUTER_MODEL",""),dataset=DATASET)
            print(json.dumps(result,indent=2))
            return 0
        if args.command == "catalogue":
            result = {k: v for k, v in registry.items() if k != "documents"}
            if args.output:
                write_json_immutable(args.output, result)
        else:
            if args.command != "validate":
                source, target = args.snapshot.resolve(), args.output.resolve()
                if source.is_relative_to(target) or target.is_relative_to(source):
                    raise ValueError("Output must be separate from legacy/source snapshots")
            if args.command == "context":
                result = build_context(args.snapshot, extended=args.extended, max_chars=args.context_chars)
                write_json_immutable(args.output / "context.json", result)
            elif args.command == "collect":
                load_env(ROOT / ".env")
                result = collect_context(args.snapshot, args.output, reader=GitHubReader())
            elif args.command == "propose":
                load_env(ROOT / ".env")
                from .device import inspect_device
                runtime=inspect_device()
                from .pipeline import run_proposals
                # Delay Supabase/ML initialization until a pattern is applicable.
                class LazyRetriever:
                    identity = {"dataset_sha256": registry["dataset_sha256"]}
                    instance = None
                    def retrieve(self, pattern_id, query, *, top_k):
                        if self.instance is None:
                            from .retrieval import PatternRetriever
                            self.instance = PatternRetriever(dataset=DATASET,
                                dataset_sha256=registry["dataset_sha256"], revision=args.embedding_revision)
                            self.identity = self.instance.identity
                        return self.instance.retrieve(pattern_id, query, top_k=top_k)
                result = run_proposals(args.snapshot, args.output, registry=registry,
                    model=args.model, top_k=args.top_k, max_tokens=args.max_tokens,
                    context_chars=args.context_chars, extended=args.extended, retriever=LazyRetriever(),
                    embedding_revision=args.embedding_revision,runtime=runtime)
            else:
                from .admission import validate_output
                result = validate_output(args.output, registry, reviews=args.reviews, arm=args.arm)
        if args.command == "propose":
            print(json.dumps({"protocol": result["protocol"], "patterns_considered": result["patterns_considered"],
                              "decisions": {r["pattern_id"]: r["decision"] for r in result["outcomes"]},
                              "ci_dispatches": 0}, indent=2))
        elif args.command in {"context", "collect"}:
            print(json.dumps({"files": len(result.get("files", result.get("archived", []))),
                              "omitted": len(result.get("omitted", []))}, indent=2))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print("Stopped. Resume the same full-pattern command/output to reuse archived stages.", file=sys.stderr)
        return 130
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        print(f"Full-pattern stage stopped: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
