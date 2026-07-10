"""
utils.py
========
Cross-cutting helpers used by every other module:

* Logging setup
* Async retry-with-exponential-backoff decorator
* Phone / email / text normalization
* robots.txt compliance checking
* Simple per-domain async rate limiter
"""

from __future__ import annotations

import asyncio
import functools
import logging
import re
import sys
import time
import urllib.robotparser
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar
from urllib.parse import urlparse
import re

def clean_name(full_name: str) -> str:
    if not full_name:
        return ""
    
    # 逻辑保持不变
    if "," in full_name:
        full_name = full_name.split(",")[0]
        
    cleaned = re.sub(r'\b(principal|parent coordinator)\b', '', full_name, flags=re.IGNORECASE)
    
    return cleaned.strip()

T = TypeVar("T")

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
def setup_logging(log_dir: Path, level: str = "INFO", name: str = "school_scraper") -> logging.Logger:
    """Configure and return the application logger (console + rotating file)."""
    logger = logging.getLogger(name)
    if logger.handlers:  # avoid duplicate handlers on repeated calls
        return logger

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_dir / "scraper.log", encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    error_handler = logging.FileHandler(log_dir / "errors.log", encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)
    logger.addHandler(error_handler)

    return logger


# --------------------------------------------------------------------------
# Retry with exponential backoff (async)
# --------------------------------------------------------------------------
def retry_async(
    max_retries: int = 3,
    backoff_factor: float = 1.5,
    exceptions: tuple = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[Optional[T]]]]:
    """
    Decorator that retries an async function on failure using exponential
    backoff. Returns None (and logs) if all attempts are exhausted, rather
    than raising, so a single failing page never crashes the whole crawl.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[Optional[T]]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Optional[T]:
            logger = logging.getLogger("school_scraper")
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:  # noqa: BLE001 - intentional broad catch at boundary
                    last_exc = exc
                    delay = backoff_factor ** attempt
                    logger.warning(
                        "Attempt %d/%d failed for %s: %s (retrying in %.1fs)",
                        attempt, max_retries, getattr(func, "__name__", func), exc, delay,
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(delay)
            logger.error(
                "All %d attempts failed for %s: %s",
                max_retries, getattr(func, "__name__", func), last_exc,
            )
            return None

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Text / phone / email normalization
# --------------------------------------------------------------------------
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# North-American phone numbers, with optional country code and separators.
_PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-]?)?\(?\b(\d{3})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})\b"
)
_EMAIL_VALID_RE = re.compile(
    r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"
)


def strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities, leaving plain text."""
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub(" ", raw)
    text = unescape(text)
    return clean_text(text)


def clean_text(text: Optional[str]) -> str:
    """Trim, collapse whitespace, and drop control characters."""
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def is_valid_email(email: str) -> bool:
    """Validate an email address against a practical RFC-5322-ish pattern."""
    if not email:
        return False
    return bool(_EMAIL_VALID_RE.match(email.strip()))


def normalize_email(text: str) -> Optional[str]:
    """Extract and lower-case the first valid-looking email found in text."""
    if not text:
        return None
    match = _EMAIL_RE.search(text)
    if not match:
        return None
    candidate = match.group(0).strip().strip(".,;:").lower()
    return candidate if is_valid_email(candidate) else None


def find_all_emails(text: str) -> list[str]:
    """Return every unique, valid email address found in text (order preserved)."""
    if not text:
        return []
    found = []
    seen = set()
    for match in _EMAIL_RE.finditer(text):
        candidate = match.group(0).strip().strip(".,;:").lower()
        if is_valid_email(candidate) and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)
    return found


def normalize_phone(text: str) -> Optional[str]:
    """Extract and format the first phone number found as (XXX) XXX-XXXX."""
    if not text:
        return None
    match = _PHONE_RE.search(text)
    if not match:
        return None
    area, prefix, line = match.groups()
    return f"({area}) {prefix}-{line}"


def find_all_phones(text: str) -> list[str]:
    """Return every unique normalized phone number found in text."""
    if not text:
        return []
    found = []
    seen = set()
    for match in _PHONE_RE.finditer(text):
        area, prefix, line = match.groups()
        formatted = f"({area}) {prefix}-{line}"
        if formatted not in seen:
            seen.add(formatted)
            found.append(formatted)
    return found


_ADDR_ABBREV = {
    r"\bstreet\b": "St",
    r"\bavenue\b": "Ave",
    r"\bboulevard\b": "Blvd",
    r"\broad\b": "Rd",
    r"\bdrive\b": "Dr",
    r"\blane\b": "Ln",
    r"\bplace\b": "Pl",
    r"\bcourt\b": "Ct",
    r"\bparkway\b": "Pkwy",
    r"\bsquare\b": "Sq",
    r"\bterrace\b": "Ter",
    r"\bexpressway\b": "Expy",
}


def standardize_address(address: Optional[str]) -> str:
    """Title-case and abbreviate a raw address string for consistency."""
    if not address:
        return ""
    text = clean_text(strip_html(address))
    text = text.title()
    for pattern, repl in _ADDR_ABBREV.items():
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    # Fix common title-case artifacts like "1St" -> "1st"
    text = re.sub(r"\b(\d+)St\b", r"\1st", text)
    text = re.sub(r"\b(\d+)Nd\b", r"\1nd", text)
    text = re.sub(r"\b(\d+)Rd\b", r"\1rd", text)
    text = re.sub(r"\b(\d+)Th\b", r"\1th", text)
    text = re.sub(r"\bNy\b", "NY", text)
    return clean_text(text)


def extract_domain(url: str) -> str:
    """Return the network location (domain) of a URL, without 'www.'."""
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return netloc[4:] if netloc.startswith("www.") else netloc


# --------------------------------------------------------------------------
# robots.txt compliance
# --------------------------------------------------------------------------
class RobotsChecker:
    """Caches robots.txt parsers per-domain and answers can_fetch queries."""

    def __init__(self, user_agent: str, logger: Optional[logging.Logger] = None) -> None:
        self.user_agent = user_agent
        self.logger = logger or logging.getLogger("school_scraper")
        self._parsers: Dict[str, urllib.robotparser.RobotFileParser] = {}

    def _get_parser(self, domain: str) -> Optional[urllib.robotparser.RobotFileParser]:
        if domain in self._parsers:
            return self._parsers[domain]
        parser = urllib.robotparser.RobotFileParser()
        robots_url = f"https://{domain}/robots.txt"
        try:
            parser.set_url(robots_url)
            parser.read()
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("Could not read robots.txt for %s: %s", domain, exc)
            parser = None  # Treat missing/unreadable robots.txt as permissive
        self._parsers[domain] = parser
        return parser

    def can_fetch(self, url: str) -> bool:
        """Return True if this URL may be fetched per robots.txt (fail-open)."""
        domain = extract_domain(url)
        parser = self._get_parser(domain)
        if parser is None:
            return True
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:  # noqa: BLE001
            return True


# --------------------------------------------------------------------------
# Per-domain async rate limiter
# --------------------------------------------------------------------------
class RateLimiter:
    """Ensures a minimum delay between consecutive requests to each domain."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds
        self._last_request: Dict[str, float] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _lock_for(self, domain: str) -> asyncio.Lock:
        if domain not in self._locks:
            self._locks[domain] = asyncio.Lock()
        return self._locks[domain]

    async def wait(self, url: str) -> None:
        domain = extract_domain(url)
        lock = self._lock_for(domain)
        async with lock:
            now = time.monotonic()
            last = self._last_request.get(domain, 0.0)
            elapsed = now - last
            if elapsed < self.delay_seconds:
                await asyncio.sleep(self.delay_seconds - elapsed)
            self._last_request[domain] = time.monotonic()


@dataclass
class Timer:
    """Small context-manager-free stopwatch used for logging durations."""

    start: float = 0.0

    def __enter__(self) -> "Timer":
        self.start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        pass

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.start
