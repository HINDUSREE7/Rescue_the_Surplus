"""Optional LLM intake extractors. Rules-only is the default.

An extractor only PROPOSES field values. Confidence comes from agreement with the rule-based
parser (see agreement()), never from the model's own self-report. Extractors must never set
safe windows, expiry or status; that stays in engine.py.
"""
import json
import os
import urllib.request

CONFIDENCE_MIN = 0.7  # minimum rules/LLM agreement before LLM values are trusted; below it, fields ask
LLM_TIMEOUT_S = 3  # same budget as parser.call_llm


class LLMExtractor:
    """Base interface. extract(text) returns a dict of proposed fields, or None on failure."""

    def extract(self, text):
        raise NotImplementedError


class StubLLM(LLMExtractor):
    """STUB: deterministic, no network. It measures no real model; it returns a fixed reply
    so tests and the eval harness can exercise the agreement path without a model."""

    def __init__(self, reply=None):
        self._reply = dict(reply or {})

    def extract(self, text):
        return dict(self._reply)


class HttpLLM(LLMExtractor):
    """POSTs {"text": text} as JSON to RTS_LLM_URL and returns the decoded dict.
    Returns None on any error, timeout, or a reply that is not a JSON object."""

    def __init__(self, url):
        self.url = url

    def extract(self, text):
        body = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(self.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
                data = json.loads(resp.read(20000).decode("utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None


def get_extractor():
    """HttpLLM when RTS_LLM_URL is set, otherwise None (rules-only)."""
    url = os.environ.get("RTS_LLM_URL")
    return HttpLLM(url) if url else None


def agreement(rules_fields, llm_fields):
    """Fraction of shared keys whose values are equal. 0.0 when there are no shared keys."""
    shared = [k for k in rules_fields if k in llm_fields]
    if not shared:
        return 0.0
    same = sum(1 for k in shared if rules_fields[k] == llm_fields[k])
    return same / len(shared)
