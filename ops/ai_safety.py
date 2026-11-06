"""Local-only AI boundary.

The model is not a tool runner. This module decides what the process may
call before any socket opens. Cloud names and public hosts are refused
even when a request would otherwise succeed.
"""

from __future__ import annotations

import ipaddress
import re
from urllib.parse import urlparse

PROMPT_VERSION = "ai-evidence-20261106"
CLOUD_MARKERS = (
    "gpt-",
    "gpt_",
    "claude",
    "gemini",
    "openai/",
    "anthropic",
    "cohere",
    "command-r",
    "grok-",
    "mistral.ai",
)
ORDER_TOKENS = ("approve", "order", "buy now", "sell now", "place a trade", "open a position")
INJECTION = re.compile(
    r"(ignore (all |any |previous |prior )?instructions|system prompt|you are now|disregard|jailbreak|tool_call|</|```)",
    re.IGNORECASE,
)
NUMBER = re.compile(r"\d+\.\d+|\d{5,}")


def local_model_allowed(name):
    text = (name or "").strip().lower()
    if not text:
        return True
    return not any(marker in text for marker in CLOUD_MARKERS)


def endpoint_allowed(url):
    """Loopback or a literal private address only. No public DNS name."""
    parsed = urlparse(url or "")
    if parsed.scheme != "http" or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    host = (parsed.hostname or "").strip().lower()
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address != ipaddress.ip_address("::1"):
        return False
    return bool(address.is_loopback or address.is_private) and not address.is_link_local and not address.is_unspecified


def scrub_untrusted(text):
    raw = str(text or "").strip()
    if not raw:
        return ""
    if INJECTION.search(raw):
        return ""
    return raw[:280]


def redact_numbers(text):
    return NUMBER.sub("[withheld]", str(text or ""))


def order_language(text):
    folded = (text or "").lower()
    return any(token in folded for token in ORDER_TOKENS)


def question_requests_action(text):
    folded = (text or "").lower()
    phrases = ("buy now", "sell now", "place a trade", "place the order", "open a position", "open an order", "approve the strategy", "approve this")
    return any(phrase in folded for phrase in phrases)


def invented_numbers(text, allowed):
    """Numbers in a model sentence that were not in the supplied text."""
    corpus = " ".join(str(item) for item in (allowed or []))
    found = []
    for match in NUMBER.findall(text or ""):
        if match not in corpus and match not in found:
            found.append(match)
    return found


def call_tool(name, **_kwargs):
    """The analyst has no executable tools. A requested name is a refusal."""
    raise PermissionError(name or "unnamed")
