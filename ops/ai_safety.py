"""Local-only AI boundary.

The model is not a tool runner. This module decides what the process may
call before any socket opens. Cloud names and public hosts are refused
even when a request would otherwise succeed.
"""

from __future__ import annotations

import ipaddress
import re
import unicodedata
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
ORDER_TOKENS = (
    "approve",
    "order",
    "buy now",
    "sell now",
    "purchase",
    "place a trade",
    "place the trade",
    "open a position",
    "open the position",
)
NUMBER = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?[eE][+-]?\d+|\d+\.\d+|\d{3,}"
)
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


def _plain(text):
    return unicodedata.normalize("NFKC", str(text or ""))


def scrub_untrusted(text):
    raw = _plain(text).strip()
    if not raw:
        return ""
    if INJECTION.search(raw):
        return ""
    return raw[:280]


def redact_numbers(text):
    return NUMBER.sub("[withheld]", _plain(text))


_BLANK_SPOOF = frozenset({
    "\u115f",
    "\u1160",
    "\u3164",
    "\uffa0",
    "\u2800",
    "\u3000",
})


def suspicious_characters(text):
    """Format, combining, control, or blank-glyph characters that can hide a phrase."""
    for ch in str(text or ""):
        category = unicodedata.category(ch)
        if category in {"Cf", "Mn", "Me"}:
            return True
        if category == "Cc" and ch not in "\n\r\t":
            return True
        if category in {"Zl", "Zp"}:
            return True
        if category == "Zs" and ch != " ":
            return True
        if ch in _BLANK_SPOOF:
            return True
    return False


def policy_text(text):
    """NFKC, drop hidden characters, and fold case for the output check."""
    return _visible_text(text, lower=True)


def _visible_text(text, lower=False):
    """NFKC text with hidden characters removed. Case is kept unless ``lower`` is set."""
    out = []
    for ch in _plain(text):
        category = unicodedata.category(ch)
        if category in {"Cf", "Mn", "Me"} or (category == "Cc" and ch not in "\n\r\t"):
            continue
        if ch in _BLANK_SPOOF or category in {"Zs", "Zl", "Zp"}:
            out.append(" ")
            continue
        out.append(ch)
    cleaned = re.sub(r"\s+", " ", "".join(out)).strip()
    return cleaned.lower() if lower else cleaned


def _folded(text):
    return policy_text(text)


def unexpected_letters(text, allowed_text):
    """A non-Latin letter can redraw an order phrase or an account name.

    ASCII letters stay. A non-Latin letter is kept only when that same
    character is already in the stored facts or refs.
    """
    allowed = set()
    for ch in str(allowed_text or ""):
        if unicodedata.category(ch).startswith("L") and ch not in _ASCII_LETTERS:
            allowed.add(ch)
    for ch in str(text or ""):
        if not unicodedata.category(ch).startswith("L"):
            continue
        if ch in _ASCII_LETTERS or ch in allowed:
            continue
        return True
    return False


_ASCII_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _decimal_token(value):
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


_NUMBER_WORDS = frozenset(
    """
    zero one two three four five six seven eight nine ten
    eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen
    twenty thirty forty fifty sixty seventy eighty ninety
    hundred thousand fourscore
    """.split()
)


_GLUE = frozenset({
    "a",
    "an",
    "at",
    "for",
    "in",
    "is",
    "of",
    "on",
    "pct",
    "percent",
    "rate",
    "the",
    "to",
})
DISPLAY_NAME_MAX = 40


def display_name_token(raw):
    """Folded account name when it can be a foreign-identity token.

    One-character names and connector words are not tokens. ``Al``, ``Jo``,
    and ``Ann`` are. ``is`` and ``B`` are not, so a legacy account with one
    of those names cannot make ordinary prose fail.
    """
    compact = re.sub(r"[^a-z0-9]", "", policy_text(raw))
    if len(compact) < 2 or compact in _GLUE:
        return None
    return compact


def accept_display_name(raw):
    """Name safe to store, or None when creation or rename must refuse it.

    The check uses the same NFKC and hidden-character rules as model text.
    It does not change a role, an entitlement, or an account id.
    """
    cleaned = _visible_text(raw, lower=False)
    if not cleaned or len(cleaned) > DISPLAY_NAME_MAX:
        return None
    if display_name_token(cleaned) is None:
        return None
    return cleaned


def _number_construction(token):
    """True when the whole token is number words plus connectors.

    ``ateight`` is ``at`` + ``eight``. ``someone`` and ``weight`` are not,
    because the extra letters are not connectors. A connector by itself,
    such as ``at``, ``for``, or ``on``, is not a number.
    """
    if not token:
        return False
    pieces = sorted(set(_NUMBER_WORDS) | set(_GLUE), key=len, reverse=True)
    memo = {}

    def walk(index, saw_number):
        key = (index, saw_number)
        if key in memo:
            return memo[key]
        if index == len(token):
            memo[key] = saw_number
            return saw_number
        found = False
        for piece in pieces:
            if token.startswith(piece, index) and walk(index + len(piece), saw_number or piece in _NUMBER_WORDS):
                found = True
                break
        memo[key] = found
        return found

    return walk(0, False)


def unknown_number_words(text, allowed_text):
    """A spelled win rate is the same claim as digits, including ``e i g h t y``."""
    allowed = set(re.findall(r"[a-z]+", policy_text(allowed_text)))
    folded = policy_text(text)
    found = []
    for word in re.findall(r"[a-z]+", folded):
        if word in allowed or word in found:
            continue
        if _number_construction(word):
            found.append(word)
    for word in _NUMBER_WORDS:
        if word in allowed or word in found:
            continue
        parts = [re.escape(ch) for ch in word]
        pattern = r"(?<![a-z0-9])" + r"[^a-z0-9]*".join(parts) + r"(?![a-z0-9])"
        if re.search(pattern, folded):
            found.append(word)
    return found


def unknown_digit_runs(text, allowed):
    """Digit runs after hidden characters are removed, including a short win rate.

    A character with a Unicode numeric value is the same claim as that number,
    even when NFKC does not turn it into an ASCII digit. Digits split by a
    separator that contains no letter are one run, so ``8 0`` and ``8-0``
    are ``80``. A letter between digits keeps the runs apart.
    """
    known = set()
    for item in allowed or []:
        known.update(re.findall(r"\d+", policy_text(item)))
    folded = policy_text(text)
    joined = re.sub(r"(?<=\d)[^a-z0-9]+(?=\d)", "", folded)
    unknown = [run for run in re.findall(r"\d+", joined) if run not in known]
    for ch in str(text or ""):
        if "0" <= ch <= "9":
            continue
        value = unicodedata.numeric(ch, None)
        if value is None:
            continue
        token = _decimal_token(value)
        if token not in known and token not in unknown:
            unknown.append(token)
    for token in re.findall(r"[a-z]+", folded):
        value = _glued_roman_value(token)
        if value is None:
            continue
        token = str(value)
        if token not in known and token not in unknown:
            unknown.append(token)
    for match in re.finditer(r"(?<![a-z0-9])([ivxlcdm](?:[^a-z0-9]+[ivxlcdm]){2,})(?![a-z0-9])", folded):
        value = _roman_value(re.sub(r"[^ivxlcdm]", "", match.group(1)))
        if value is None:
            continue
        token = str(value)
        if token not in known and token not in unknown:
            unknown.append(token)
    return unknown


_IDENTIFIER = re.compile(r"[a-z0-9]+(?:[-_./:][a-z0-9]+){1,}")


_ROMAN = re.compile(r"m{0,3}(cm|cd|d?c{0,3})(xc|xl|l?x{0,3})(ix|iv|v?i{0,3})")
_ROMAN_IGNORE = frozenset({"mix"})
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _roman_value(token):
    """ASCII Roman numerals such as LXXX. A normal word such as mix is not a number.

    ``vi``, ``iv``, and ``ii`` are intentionally not numerals. Each is shorter
    than 3 and has none of ``x``, ``l``, ``c``, ``d``, or ``m``. Gluing a
    connector in front of one of those short forms does not change that.
    ``isvi`` stays a word. ``viii`` and ``isviii`` do not.
    """
    if not token or token in _ROMAN_IGNORE or not re.fullmatch(_ROMAN, token):
        return None
    if len(token) < 3 and not any(ch in token for ch in "xlcdm"):
        return None
    total = 0
    prev = 0
    for ch in reversed(token):
        value = _ROMAN_VALUES[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total or None


def _glued_roman_value(token):
    """``viii`` itself, or the same numeral glued to connectors such as ``is`` or ``the``.

    A peeled core must be at least three characters. Otherwise ``Ada`` becomes
    ``d`` after the connector ``a`` is removed from both ends, and ``d`` is 500.
    """
    if not token:
        return None
    direct = _roman_value(token)
    if direct is not None:
        return direct
    glues = sorted(_GLUE, key=len, reverse=True)
    text = token
    for _ in range(8):
        if len(text) >= 3 and text != token:
            value = _roman_value(text)
            if value is not None:
                return value
        peeled = None
        for glue in glues:
            if text.startswith(glue) and len(text) > len(glue):
                peeled = text[len(glue):]
                break
            if text.endswith(glue) and len(text) > len(glue):
                peeled = text[:-len(glue)]
                break
        if peeled is None:
            break
        text = peeled
    if text != token and len(text) >= 3:
        return _roman_value(text)
    return None


def unknown_identifiers(text, allowed_text):
    haystack = policy_text(allowed_text)
    found = []
    for token in _IDENTIFIER.findall(policy_text(text)):
        if token not in haystack and token not in found:
            found.append(token)
    words = _identifier_words(text)
    allowed_words = " ".join(_identifier_words(allowed_text))
    for index in range(len(words) - 2):
        chunk = words[index:index + 3]
        if not all(len(part) >= 4 for part in chunk):
            continue
        token = "-".join(chunk)
        phrase = " ".join(chunk)
        if token in haystack or phrase in haystack or token in found or phrase in allowed_words:
            continue
        found.append(token)
    for token in re.findall(r"\b[0-9a-f]{8,}\b", policy_text(text)):
        if token not in haystack and token not in found:
            found.append(token)
    return found


_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t"})
_ORDER_PAIRS = (
    ("buy", "now"),
    ("sell", "now"),
    ("buyit", "now"),
    ("sellit", "now"),
    ("place", "trade"),
    ("open", "position"),
    ("open", "order"),
)


def _identifier_words(text):
    cleaned = policy_text(text).replace("\u2019", "'").replace("\u2018", "'")
    cleaned = re.sub(r"'s\b", "", cleaned).replace("'", "")
    return re.findall(r"[a-z0-9]+", cleaned)


def order_language(text):
    """Order instructions, not a bare mention of buying.

    ``buy now``, ``buyitnow``, and ``buyit now`` are instructions. ``buying now``
    is ordinary commentary. Neither form can open an order. The route still
    forces ``approved`` and ``order_opened`` false.
    """
    folded = _folded(text).translate(_LEET)
    if any(token in folded for token in ORDER_TOKENS):
        return True
    compact = re.sub(r"[^a-z0-9]", "", folded)
    if any(token in compact for token in _ORDER_COMPACT):
        return True
    words = set(re.findall(r"[a-z]+", folded))
    return any(left in words and right in words for left, right in _ORDER_PAIRS)


_ORDER_COMPACT = (
    "approve",
    "order",
    "buynow",
    "sellnow",
    "buyitnow",
    "sellitnow",
    "placeatrade",
    "placeanorder",
    "openaposition",
    "openanorder",
)


def question_requests_action(text):
    folded = _folded(text)
    phrases = ("buy now", "sell now", "place a trade", "place the order", "open a position", "open an order", "approve the strategy", "approve this")
    return any(phrase in folded for phrase in phrases)


def _numeric_tokens(text):
    return [match.replace(",", "") for match in NUMBER.findall(_plain(text))]


def invented_numbers(text, allowed):
    """Whole numbers in a model sentence that were not tokens in the supplied text.

    A longer stored token does not authorise a shorter price hidden inside it,
    and thousands separators do not hide a price.
    """
    allowed_tokens = set()
    for item in allowed or []:
        allowed_tokens.update(_numeric_tokens(str(item)))
    found = []
    for raw in NUMBER.findall(_plain(text)):
        key = raw.replace(",", "")
        if key not in allowed_tokens and raw not in found:
            found.append(raw)
    return found


def foreign_evidence(items, allowed_text):
    """Evidence citations that are not present in the stored facts or refs.

    A short label such as ``observation`` is kept when that word is already
    in the facts. An invented id or a phrase the desk did not supply is not.
    """
    haystack = _plain(allowed_text).lower()
    bad = []
    for item in items or []:
        text = _plain(item).strip()
        if not text:
            continue
        if text.lower() in haystack:
            continue
        bad.append(text)
    return bad


def call_tool(name, **_kwargs):
    """The analyst has no executable tools. A requested name is a refusal."""
    raise PermissionError(name or "unnamed")
