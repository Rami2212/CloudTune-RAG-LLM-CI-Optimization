"""Bounded OpenRouter JSON transport used by the evaluation optimizer.

The one-shot daemon worker enforces a *whole-request* deadline on Windows and
Linux. urllib's socket timeout alone does not cap an HTTP chunked response.
Timed-out calls are never retried automatically. The caller checkpoints a
manual-retry pause; late worker results cannot write evaluation artifacts.
"""
from __future__ import annotations

import json
import threading
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


OPENROUTER_REQUEST_SECONDS = 60


class OpenRouterPaused(RuntimeError):
    """OpenRouter did not provide a usable response; manual retry is required."""

    def __init__(self, reason: str, *, http_status: int | None = None):
        super().__init__(reason)
        self.http_status = http_status


def request_openrouter_json(request, *, opener=None, deadline_seconds: float = OPENROUTER_REQUEST_SECONDS):
    """Read one entire JSON response with a hard caller deadline and no retries.

    Work occurs in a daemon thread so a blocked SSL read cannot prevent the
    controller from returning on Windows (which lacks signal.alarm). Only the
    caller writes archived results, so late replies can never overwrite state.
    The underlying socket can remain open briefly after timeout; the controller
    pauses immediately rather than dispatching another request in parallel.
    """
    if not 0 < deadline_seconds <= OPENROUTER_REQUEST_SECONDS:
        raise ValueError("OpenRouter deadline must be between 0 and 60 seconds")
    opener = opener or urlopen
    finished = threading.Event()
    response = {}

    def send_once():
        try:
            with opener(request, timeout=deadline_seconds) as stream:
                response["reply"] = json.load(stream)
        except Exception as exc:
            response["exception"] = exc
        finally:
            finished.set()

    worker = threading.Thread(target=send_once, name="cloudtune-openrouter-request", daemon=True)
    worker.start()
    if not finished.wait(deadline_seconds):
        raise OpenRouterPaused(
            f"OpenRouter API request exceeded {int(deadline_seconds)}s; "
            "the outcome is uncertain, and no automatic retry was sent")

    error = response.get("exception")
    if error is not None:
        if isinstance(error, HTTPError):
            raise OpenRouterPaused(
                f"OpenRouter HTTP {error.code}; request retained, no paid fallback or automatic retry",
                http_status=error.code) from None
        if isinstance(error, (URLError, TimeoutError, OSError)):
            raise OpenRouterPaused(
                f"OpenRouter connection failed ({type(error).__name__}); "
                "request retained, no automatic retry") from None
        if isinstance(error, json.JSONDecodeError):
            raise OpenRouterPaused("OpenRouter returned invalid JSON; request retained") from None
        raise OpenRouterPaused(
            f"OpenRouter response could not be read ({type(error).__name__}); request retained") from None

    reply = response.get("reply")
    if not isinstance(reply, dict):
        raise OpenRouterPaused("OpenRouter response was not a JSON object; request retained")
    if reply.get("error"):
        # Provider-level errors can arrive with HTTP 200. Do not archive the
        # response as a completed candidate; permit explicit manual resume.
        raise OpenRouterPaused("OpenRouter returned a provider error; request retained")
    return reply
