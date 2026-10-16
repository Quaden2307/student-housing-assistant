"""Strip contact details from listing text at parse time (HANDOFF section 5, privacy rule).

Emails (plain or written out as "me at gmail dot com"), North American phone numbers (in
digits, spaced digits or spelled-out digits) and the names that follow contact phrases are
replaced with a marker before anything is stored. Names are found by a narrow rule, not a
language model: the capitalised words right after "contact", "call", "text", "ask for",
"my name is" and the usual sign-offs ("Thanks, Sam"). The poster's profile name on Kijiji is
never read at all, and :func:`scrub_page` removes it from a whole page before the raw copy
is written under ``data/raw``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable

REDACTED = "[contact removed]"

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", re.IGNORECASE)
# "me at gmail dot com", "me [at] gmail.com". A literal dot must be followed by a non-space
# so "at Columbia. Close to campus" is a sentence, not an address.
_AT = r"(?:\[\s*at\s*\]|\(\s*at\s*\)|\s+at\s+)"
_DOT = r"(?:\.(?=\S)|\s*\[\s*dot\s*\]\s*|\s*\(\s*dot\s*\)\s*|\s+dot\s+)"
OBFUSCATED_EMAIL_RE = re.compile(
    rf"\b[\w.+-]+\s*{_AT}\s*[\w-]+(?:{_DOT}[\w-]+)*{_DOT}(?:com|ca|net|org|edu)\b",
    re.IGNORECASE,
)
# 519-555-0199, (519) 555 0199, 519.555.0199, +1 519 555 0199, 5195550199, and the loose
# spacings seen in ads: "(519 )555 0199", "519 - 555 - 0199", "519 555 01 99". The
# look-arounds stop it matching inside longer digit runs such as prices with no separators.
_SEP = r"[\s.-]{0,3}"
PHONE_RE = re.compile(
    rf"(?<!\d)(?:\+?1{_SEP})?(?:\(\s?)?\d{{3}}\s?\)?{_SEP}\d{{3}}{_SEP}\d{{2}}[\s.-]{{0,2}}\d{{2}}(?!\d)"
)
# "5 1 9 5 5 5 0 1 9 9": ten digits one apart.
SPACED_PHONE_RE = re.compile(r"(?<!\d)\d(?:[\s.-]\d){9}(?!\d)")
# "five one nine 555 0199": runs of digit words mixed with digits; _spelled_phone decides.
DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}  # fmt: skip
_DIGIT_TOKEN = r"(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|\d{1,4})"
WORD_PHONE_RE = re.compile(rf"\b(?:{_DIGIT_TOKEN}\b[\s.()-]*){{4,}}", re.IGNORECASE)
# A seven-digit local number only counts right after a contact word: "call 555-0199".
LOCAL_PHONE_RE = re.compile(
    r"(\b(?:call|text|phone|cell|tel|contact|whatsapp|reach)\b\W{0,12})\d{3}[\s.-]?\d{4}(?!\d)",
    re.IGNORECASE,
)

# Words that follow a contact verb without being a name ("Contact Me", "Call Today").
_NOT_A_NAME = (
    "me|us|the|a|an|at|for|or|and|now|today|tonight|kijiji|landlord|landlords|owner|owners|"
    "office|via|by|if|to|with|your|our|my|this|that|through|directly|asap|anytime|only|"
    "please|before|after|in|on|about|available|information|info|details|address|number|"
    "out|first|during|between|property|management|manager|agent|tenant|tenants|building|"
    "rental|rentals|phone|email|text|call|message|whatsapp|here|below|above|back|soon|"
    "preferred|ad|serious|leasing|student|students|waterloo|kitchener|uw|laurier|"
    "mon|tue|tues|wed|thu|thurs|fri|sat|sun|monday|tuesday|wednesday|thursday|friday|"
    "saturday|sunday|am|pm|anytime|immediately|asap|via|whatsapp|team|thanks|thank"
)
_NAME = rf"(?!(?i:{_NOT_A_NAME})\b)[A-Z][a-z]+(?:\s+(?!(?i:{_NOT_A_NAME})\b)[A-Z][a-z]+)?"
NAME_AFTER_PHRASE_RE = re.compile(
    rf"(\b(?i:contact|call|text|message|reach|e-?mail|whatsapp|ask for|speak (?:to|with)|"
    rf"talk to|my name is|my name's)\s+)({_NAME}(?:\s*(?:or|and|&|/)\s*{_NAME})?)"
)
SIGNOFF_RE = re.compile(
    rf"(\b(?i:thanks|thank you|many thanks|regards|best regards|kind regards|warm regards|"
    rf"cheers|sincerely|best)[,!.]?\s*[-–—]?\s*)({_NAME})(?=\s*(?:$|[.!,]))",
    re.MULTILINE,
)
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)


def _redact_group(group: int) -> Callable[[re.Match[str]], str]:
    """Return a ``re.sub`` callback that replaces only ``group`` of the match."""

    def replace(match: re.Match[str]) -> str:
        start, end = match.span(group)
        return match.string[match.start() : start] + REDACTED + match.string[end : match.end()]

    return replace


def _spelled_phone(match: re.Match[str]) -> str:
    """Redact a run of digit words and digits when it adds up to a phone number."""
    tokens = re.findall(r"[a-z]+|\d+", match.group(0).lower())
    words = sum(1 for t in tokens if t in DIGIT_WORDS)
    digits = sum(len(t) if t.isdigit() else 1 for t in tokens)
    if words >= 3 and 7 <= digits <= 11:
        return REDACTED + match.group(0)[len(match.group(0).rstrip()) :]
    return match.group(0)


def strip_contact_info(text: str | None) -> str | None:
    """Return ``text`` with emails, phone numbers and names after contact phrases replaced.

    Every removed item becomes ``[contact removed]``. Prices, dates, postal codes and
    street numbers are left alone.
    """
    if text is None:
        return None
    out = EMAIL_RE.sub(REDACTED, text)
    out = OBFUSCATED_EMAIL_RE.sub(REDACTED, out)
    out = PHONE_RE.sub(REDACTED, out)
    out = SPACED_PHONE_RE.sub(REDACTED, out)
    out = WORD_PHONE_RE.sub(_spelled_phone, out)
    out = LOCAL_PHONE_RE.sub(_redact_local, out)
    out = NAME_AFTER_PHRASE_RE.sub(_redact_group(2), out)
    out = SIGNOFF_RE.sub(_redact_group(2), out)
    return out


def redact_url(url: str | None) -> str | None:
    """Return a listing URL with contact details removed from its slug.

    Kijiji builds the slug from the title, so a phone number in the title lands in the URL
    (``.../1-bedroom-available-519-555-0199/1742392485``). The page is resolved by the
    trailing ad id, so the slug can be shortened freely.
    """
    if not url:
        return url
    base, _, ad_id = url.rpartition("/")
    base, _, slug = base.rpartition("/")
    words = slug.replace("-", " ")
    stripped = strip_contact_info(words)
    if stripped == words:
        return url
    clean = "-".join(stripped.replace(REDACTED, " ").split()) or "listing"
    return f"{base}/{clean}/{ad_id}"


def _redact_local(match: re.Match[str]) -> str:
    return match.group(1) + REDACTED


def scrub_page(html: str) -> str:
    """Return a Kijiji page with the poster's name, phone and listing contact details removed.

    Inside ``__NEXT_DATA__`` every poster profile name becomes ``[removed]``, every
    ``posterInfo.phoneNumber`` becomes null, and listing titles and descriptions go through
    :func:`strip_contact_info`. The profile name is also removed from the server-rendered
    HTML around the JSON. A page without a parseable ``__NEXT_DATA__`` is returned as is.
    """
    match = NEXT_DATA_RE.search(html)
    if not match:
        return html
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return html
    state = (data.get("props") or {}).get("pageProps", {}).get("__APOLLO_STATE__") or {}
    names: list[str] = []
    for key, entity in state.items():
        if not isinstance(entity, dict):
            continue
        if key.startswith("StandardProfileV2:") and entity.get("name"):
            names.append(str(entity["name"]))
            entity["name"] = "[removed]"
        poster = entity.get("posterInfo")
        if isinstance(poster, dict) and "phoneNumber" in poster:
            poster["phoneNumber"] = None
        for field in ("title", "description"):
            if isinstance(entity.get(field), str):
                entity[field] = strip_contact_info(entity[field])
    html = html[: match.start(1)] + encode_next_data(data) + html[match.end(1) :]
    for name in names:
        if len(name) >= 3:
            html = re.sub(rf"\b{re.escape(name)}\b", "[removed]", html)
    return html


def encode_next_data(data: dict) -> str:
    """Serialise ``__NEXT_DATA__`` the way Next.js does: compact, with ``<`` escaped."""
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def hash_id(value: str | None) -> str | None:
    """Return a salted, truncated SHA-256 of a pseudonymous id such as a poster account id.

    The salt comes from ``HOUSING_HASH_SALT`` (set it in ``.env``), so the stored hash cannot
    be mapped back to the site's id by anyone without the salt. Poster ids are short numbers,
    so a known salt would make the hash reversible by brute force: without one this raises.
    """
    if value is None:
        return None
    salt = os.environ.get("HOUSING_HASH_SALT")
    if not salt:
        raise RuntimeError("HOUSING_HASH_SALT is not set; put a random string in .env")
    return hashlib.sha256(f"{salt}:{value}".encode()).hexdigest()[:16]
