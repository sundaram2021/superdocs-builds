"""Optional second opinion on a proposed change, using a Haiku class model.

This is a reviewer, never a writer. It never produces letter text and never
produces a figure. The deterministic comparison in run.py is what decides
whether a change is approved, and it can veto on its own. This step only adds a
human readable note to the run report, and the run works fine without it.
"""

import json
import os
import urllib.error
import urllib.request

MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
API_URL = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/") + "/v1/messages"

PROMPT = """You are auditing one edit to a legally approved letter paragraph.

APPROVED TEMPLATE (placeholders in braces are meant to be replaced):
{approved}

WHAT THE EDITOR RETURNED:
{returned}

Answer in one line, starting with either MATCH or DRIFT. Say MATCH if the returned
text differs from the template only by placeholder values being filled in. Say DRIFT
if any approved word, ordering, or punctuation outside the placeholders changed.
"""


def available():
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def review(approved_text, returned_text):
    """Return a short note string, or None when the reviewer is unavailable."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 120,
        "messages": [{"role": "user", "content": PROMPT.format(
            approved=approved_text, returned=returned_text)}],
    }).encode("utf-8")
    request = urllib.request.Request(API_URL, data=body, headers={
        "content-type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
    })
    try:
        response = urllib.request.urlopen(request, timeout=120)
        payload = json.loads(response.read().decode("utf-8"))
        return payload["content"][0]["text"].strip()
    except (urllib.error.URLError, KeyError, IndexError, ValueError) as error:
        return "reviewer unavailable: {0}".format(str(error)[:120])
