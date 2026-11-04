"""Real provider/retriever smoke using only an explicitly synthetic source."""
from __future__ import annotations

from pathlib import Path

from evaluation.repository_preparation import write_immutable, write_json_immutable
from .device import inspect_device
from .pipeline import run_proposals
from .registry import digest
from .retrieval import PatternRetriever

WORKFLOW = """name: Synthetic matrix fixture
on: [push, workflow_dispatch]
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        cell: [failure, slow-a, slow-b]
    steps:
      - uses: actions/checkout@v4
      - name: Synthetic workload
        env:
          CELL: ${{ matrix.cell }}
        run: python fixture.py
"""
SCRIPT = """# Synthetic development source. This file is never executed locally.
# The controlled matrix contract permits cancelling remaining cells after one
# cell has reported failure. All cells must finish in the all-success control.
import os
import sys
import time
if os.environ['CELL'] == 'failure':
    time.sleep(1)
    sys.exit(1)
time.sleep(5)
print('synthetic fixture')
"""


def run_smoke(output: Path, *, registry: dict, model: str, dataset: Path,
              proposer=run_proposals, retriever_factory=PatternRetriever, device_checker=inspect_device):
    runtime=device_checker()
    source=output/"synthetic-source"
    write_immutable(source/"source/original.yml",WORKFLOW.encode())
    write_immutable(source/"source/files/fixture.py",SCRIPT.encode())
    write_json_immutable(source/"source/files_manifest.json",{"archived":[{"path":"fixture.py","sha256":digest(SCRIPT.encode())}],"omitted":[]})
    write_json_immutable(source/"manifest.json",{"repo_id":"synthetic/development-only","source_commit_sha":"0"*40,
        "source_tree_sha":"0"*40,"workflow_path":".github/workflows/fixture.yml","workflow_sha256":digest(WORKFLOW.encode()),
        "required_checks":{"status":"synthetic_fixture_contract","names":["test"],
            "matrix_contract":"All success cells must complete. After a cell fails, remaining cells may be cancelled; full failure diagnostics are not required."},
        "ci_history":{"status":"not_collected"},"evidence_scope":"synthetic_development_fixture"})
    bundle=output/"evidence.json"
    write_immutable(output/"contract.txt",b"Synthetic matrix: fail-fast is explicitly permitted after failure. This is a declared fixture contract, not an observed repository fact.\n")
    facts={k:{"status":"VERIFIED","verified_by":"synthetic_fixture_definition",
              "value":"Matrix cells may be cancelled after a failure; all-pass execution must retain all cells.",
              "artifacts":[{"path":"contract.txt","sha256":digest((output/"contract.txt").read_bytes())}]}
           for k in ("matrix_contract","failure_policy")}
    write_json_immutable(bundle,{"source_commit_sha":"0"*40,"facts":facts})
    class Lazy:
        identity={"dataset_sha256":registry["dataset_sha256"]}
        instance=None
        def retrieve(inner,pid,query,*,top_k):
            if inner.instance is None:
                inner.instance=retriever_factory(dataset=dataset,dataset_sha256=registry["dataset_sha256"])
                inner.identity=inner.instance.identity
            return inner.instance.retrieve(pid,query,top_k=top_k)
    report=proposer(source,output/"proposals",registry=registry,model=model,
                    top_k=2,max_tokens=24000,evidence_bundle=bundle,retriever=Lazy(),runtime=runtime)
    return {"scope":"synthetic_live_provider_smoke","patterns_considered":report["patterns_considered"],
            "decisions":{r["pattern_id"]:r["decision"] for r in report["outcomes"]},
            "ci_dispatches":0,"runtime":runtime,"repository_set_started":False}
