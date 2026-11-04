"""Fail before model calls when the requested embedding device is unavailable."""
from __future__ import annotations

import os
import re


def inspect_device(*, torch_module=None, requested=None) -> dict:
    if torch_module is None:
        import torch as torch_module
    requested = requested or os.environ.get("CLOUDTUNE_RAG_DEVICE", "cpu")
    if requested != "cpu" and not re.fullmatch(r"cuda(?::\d+)?", requested):
        raise ValueError("CLOUDTUNE_RAG_DEVICE must be cpu, cuda or cuda:N")
    available = bool(torch_module.cuda.is_available())
    result = {"requested_device": requested, "cuda_available": available,
              "torch_version": str(torch_module.__version__),
              "cuda_build": torch_module.version.cuda, "actual_device": "cpu"}
    if requested.startswith("cuda"):
        index = int(requested.partition(":")[2] or 0)
        if not available or index >= torch_module.cuda.device_count():
            raise RuntimeError("Requested CUDA device is unavailable. Enable the dGPU or explicitly select cpu before starting; no CPU fallback occurred.")
        # An allocation plus synchronization detects driver/device failures that
        # is_available alone cannot establish. No model or network is involved.
        probe = torch_module.ones(1, device=f"cuda:{index}")
        torch_module.cuda.synchronize(index)
        result.update(actual_device=str(probe.device), gpu_name=torch_module.cuda.get_device_name(index))
    return result
