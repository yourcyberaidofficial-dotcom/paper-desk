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
    "gpt4",
    "chatgpt",
    "claude",
    "gemini",
    "openai/",
    "anthropic",
    "cohere",
    "command-r",
    "grok-",
    "mistral.ai",
    "o1-",
    "o3-",
)
ORDER_TOKENS = ("approve", "order", "buy now", "sell now", "place a trade", "open a position")
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d{3,}")
_RFC1918 = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
)
INJECTION = re.compile(
    r"(ignore (all |any |previous |prior )?instructions|system prompt|you are now|disregard|jailbreak|tool_call|</|```)",
    re.IGNORECASE,
)


def local_model_allowed(name):
    text = (name or "").strip().lower()
    if not text:
        return True
    return not any(marker in text for marker in CLOUD_MARKERS)


def endpoint_allowed(url):
    """Loopback or RFC1918 only. Documentation, reserved, and public hosts are refused."""
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
    if address.version == 6:
        return address == ipaddress.ip_address("::1")
    if address.is_loopback:
        return True
    return any(address in network for network in _RFC1918)


def listener_allowed(host):
    """Refuse a wildcard or public bind. Ollama must not listen on every interface."""
    text = (host or "").strip().lower()
    if text in {"", "0.0.0.0", "::", "[::]", "*"}:
        return False
    return endpoint_allowed("http://" + text)


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
    folded = re.sub(r"\s+", " ", (text or "").lower().replace("\u00a0", " "))
    return any(token in folded for token in ORDER_TOKENS)


def question_requests_action(text):
    folded = re.sub(r"\s+", " ", (text or "").lower().replace("\u00a0", " "))
    phrases = ("buy now", "sell now", "place a trade", "place the order", "open a position", "open an order", "approve the strategy", "approve this")
    return any(phrase in folded for phrase in phrases)


def _numeric_tokens(text):
    return [match.replace(",", "") for match in NUMBER.findall(text or "")]


def invented_numbers(text, allowed):
    """Whole numbers in a model sentence that were not tokens in the supplied text.

    A longer stored token does not authorise a shorter price hidden inside it,
    and thousands separators do not hide a price.
    """
    allowed_tokens = set()
    for item in allowed or []:
        allowed_tokens.update(_numeric_tokens(str(item)))
    found = []
    for raw in NUMBER.findall(text or ""):
        key = raw.replace(",", "")
        if key not in allowed_tokens and raw not in found:
            found.append(raw)
    return found


def call_tool(name, **_kwargs):
    """The analyst has no executable tools. A requested name is a refusal."""
    raise PermissionError(name or "unnamed")
