"""Polite HTTP fetching with raw storage (HANDOFF section 4, blocking playbook).

Every scraper goes through :class:`Fetcher`:

- one worker, one request every 2 to 3 seconds, one realistic User-Agent;
- robots.txt fetched once per host per run and checked with wildcard-aware matching
  (``urllib.robotparser`` ignores ``*`` and waves through URLs Kijiji forbids);
- retries with back-off on connection errors and 5xx, and a hard stop
  (:class:`BlockedError`) on 403, 429 or a bot-challenge page, whatever its status code;
- every response body saved gzipped under ``data/raw/<source>/<date>/<name>.<ext>.gz``
  with a ``.meta.json`` beside it, after an optional scrub of personal data. A repeat call
  the same day returns the saved copy unless ``refresh`` is set: detail pages are served
  from that cache so parsers can be re-run offline, index pages are always fetched fresh.
"""

from __future__ import annotations

import gzip
import json
import logging
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests

from housing.paths import raw_dir

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}
# Page titles of the interstitials Cloudflare, Fastly and Vercel serve to suspected bots.
CHALLENGE_MARKERS = ("<title>Just a moment...", "<title>Client Challenge", "Security Checkpoint")


def utc_now_iso() -> str:
    """Return the current UTC time as ``YYYY-MM-DDTHH:MM:SSZ`` (the project's timestamp format)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FetchError(Exception):
    """A request failed for good after retries.

    Args:
        message: What went wrong.
        status: The HTTP status that ended the attempts, or None when there was no response.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class BlockedError(FetchError):
    """403, 429 or a bot-challenge page. The caller must stop the sweep, not retry."""


class RobotsDisallowed(FetchError):
    """robots.txt forbids this URL for ``User-agent: *``."""


@dataclass(frozen=True)
class FetchResult:
    """One fetched page and where its raw body is stored."""

    url: str
    status: int
    text: str
    path: Path
    fetched_at: str
    from_cache: bool


class RobotsRules:
    """``Allow`` and ``Disallow`` rules for ``User-agent: *`` with ``*`` and ``$`` wildcards.

    The longest matching rule wins and ``Allow`` wins a tie, which is how Google and Bing
    evaluate robots.txt. A path with no matching rule is allowed.
    """

    def __init__(self, text: str) -> None:
        self._rules: list[tuple[bool, str, re.Pattern[str]]] = []
        applies = False
        in_header = False  # inside a run of User-agent lines that open a group
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            field, _, value = line.partition(":")
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                if not in_header:
                    applies, in_header = False, True
                applies = applies or value == "*"
            else:
                in_header = False
                if applies and field in ("allow", "disallow") and value:
                    self._rules.append((field == "allow", value, self._compile(value)))

    @staticmethod
    def _compile(pattern: str) -> re.Pattern[str]:
        anchored = pattern.endswith("$")
        body = pattern[:-1] if anchored else pattern
        regex = ".*".join(re.escape(part) for part in body.split("*"))
        return re.compile("^" + regex + ("$" if anchored else ""))

    def allows(self, path: str) -> bool:
        """Return True if ``path`` (including any query string) may be fetched."""
        best: tuple[int, bool] | None = None
        for allow, pattern, regex in self._rules:
            if not regex.match(path):
                continue
            if best is None or len(pattern) > best[0] or (len(pattern) == best[0] and allow):
                best = (len(pattern), allow)
        return True if best is None else best[1]


class Fetcher:
    """Rate-limited, robots-aware GET with raw storage. One instance per source per run.

    Args:
        source: Raw-storage folder name, e.g. ``"kijiji"``.
        min_delay: Minimum seconds between requests; the actual delay is uniform in
            ``[min_delay, max_delay]``.
        max_delay: Maximum seconds between requests.
        timeout: Per-request timeout in seconds.
        max_attempts: Attempts per URL before giving up on connection errors and 5xx.
        session: A ``requests.Session`` to use; tests inject a fake one.
    """

    def __init__(
        self,
        source: str,
        *,
        min_delay: float = 2.0,
        max_delay: float = 3.0,
        timeout: float = 20.0,
        max_attempts: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        self.source = source
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.session = session or requests.Session()
        self.session.headers.update(HEADERS)
        self.requests_made = 0
        self._last_request = 0.0
        self._robots: dict[str, RobotsRules] = {}

    @property
    def day_dir(self) -> Path:
        """Today's raw-storage folder, ``data/raw/<source>/<YYYY-MM-DD>``."""
        return raw_dir() / self.source / datetime.now(UTC).strftime("%Y-%m-%d")

    def get(
        self,
        url: str,
        name: str,
        *,
        ext: str = "html",
        refresh: bool = False,
        check_robots: bool = True,
        scrub: Callable[[str], str] | None = None,
    ) -> FetchResult:
        """Return the page at ``url``, from today's raw store if present, else from the network.

        Args:
            url: Absolute URL.
            name: File stem for the raw copy, e.g. ``"index_rooms_p1"``.
            ext: File extension for the raw copy (``html`` or ``txt``).
            refresh: Fetch again even if today's copy exists. Index pages pass this so a
                snapshot is always a real sighting; detail pages use the cache.
            check_robots: Consult robots.txt first (off only for robots.txt itself).
            scrub: Applied to the decoded body before it is stored and returned, so the raw
                copy never holds what the privacy rule forbids (``housing.parse.pii``).

        Raises:
            RobotsDisallowed: robots.txt forbids the URL.
            BlockedError: 403, 429 or a challenge page; stop the sweep.
            FetchError: Any other failure after retries.
        """
        path = self.day_dir / f"{name}.{ext}.gz"
        meta_path = self.day_dir / f"{name}.meta.json"
        if path.exists() and not refresh:
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            text = gzip.decompress(path.read_bytes()).decode(
                meta.get("encoding") or "utf-8", "replace"
            )
            return FetchResult(
                url, meta.get("status", 200), text, path, meta.get("fetched_at", ""), True
            )

        parts = urlsplit(url)
        if check_robots:
            target = parts.path + (f"?{parts.query}" if parts.query else "")
            if not self.robots(f"{parts.scheme}://{parts.netloc}").allows(target):
                raise RobotsDisallowed(f"robots.txt disallows {url}")

        response = self._request(url)
        fetched_at = utc_now_iso()
        encoding = response.encoding or "utf-8"
        text = response.content.decode(encoding, "replace")
        body = response.content
        if scrub is not None:
            text = scrub(text)
            body = text.encode(encoding, "replace")
        self.day_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(body))
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "final_url": response.url,
                    "status": response.status_code,
                    "fetched_at": fetched_at,
                    "content_type": response.headers.get("Content-Type"),
                    "encoding": encoding,
                    "bytes": len(body),
                    "scrubbed": scrub is not None,
                },
                indent=1,
            )
        )
        return FetchResult(url, response.status_code, text, path, fetched_at, False)

    def robots(self, base_url: str) -> RobotsRules:
        """Return the parsed robots.txt for ``base_url``'s host, fetched once per run.

        A 4xx answer (no robots.txt) means no restrictions. Any other failure (5xx, no
        network) is raised: without a robots decision nothing else is fetched.
        """
        host = urlsplit(base_url).netloc
        if host not in self._robots:
            try:
                result = self.get(
                    f"{base_url.rstrip('/')}/robots.txt",
                    "robots",
                    ext="txt",
                    refresh=True,
                    check_robots=False,
                )
                self._robots[host] = RobotsRules(result.text)
            except BlockedError:
                raise
            except FetchError as exc:
                if exc.status is None or not 400 <= exc.status < 500:
                    raise
                log.warning("no robots.txt for %s (%s); assuming no rules", host, exc)
                self._robots[host] = RobotsRules("")
        return self._robots[host]

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_request
        delay = random.uniform(self.min_delay, self.max_delay)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        self._last_request = time.monotonic()

    def _backoff(self, attempt: int) -> None:
        if attempt < self.max_attempts:
            time.sleep(5 * attempt)

    def _request(self, url: str) -> requests.Response:
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._wait()
            self.requests_made += 1
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = exc
                log.warning("attempt %d/%d failed for %s: %s", attempt, self.max_attempts, url, exc)
                self._backoff(attempt)
                continue
            status = response.status_code
            if status in (403, 429) or _looks_like_challenge(response.text):
                raise BlockedError(
                    f"HTTP {status} with a block or challenge for {url}; stop for 24 hours",
                    status=status,
                )
            if 500 <= status < 600:
                last_error = FetchError(f"HTTP {status}", status=status)
                log.warning("attempt %d/%d got %d for %s", attempt, self.max_attempts, status, url)
                self._backoff(attempt)
                continue
            if status != 200:
                raise FetchError(f"HTTP {status} for {url}", status=status)
            return response
        status = last_error.status if isinstance(last_error, FetchError) else None
        raise FetchError(
            f"gave up on {url} after {self.max_attempts} attempts: {last_error}", status=status
        )


def scrub_stored_pages(directory: Path, scrub: Callable[[str], str]) -> int:
    """Apply ``scrub`` in place to every ``*.html.gz`` under ``directory``; return how many changed.

    For raw pages saved before the fetcher scrubbed them. The ``.meta.json`` beside each page
    gets ``"scrubbed": true``.
    """
    changed = 0
    for path in sorted(directory.rglob("*.html.gz")):
        html = gzip.decompress(path.read_bytes()).decode("utf-8", "replace")
        clean = scrub(html)
        if clean != html:
            path.write_bytes(gzip.compress(clean.encode("utf-8")))
            changed += 1
        meta_path = path.with_name(path.name.removesuffix(".html.gz") + ".meta.json")
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            meta["scrubbed"] = True
            meta_path.write_text(json.dumps(meta, indent=1))
    return changed


def _looks_like_challenge(text: str) -> bool:
    head = text[:4000]
    return any(marker in head for marker in CHALLENGE_MARKERS)
