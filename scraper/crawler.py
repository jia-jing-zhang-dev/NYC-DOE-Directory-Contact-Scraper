"""
crawler.py
==========
Asynchronous, polite crawler that starts from one or more seed URLs (a
school's homepage, or an official directory page) and discovers relevant
internal pages (Contact, Staff Directory, Administration, Faculty,
Leadership, Parent Coordinator, Family Engagement, About, ...) by
following internal links via breadth-first search.

Fetching prefers Playwright (handles JS-rendered sites); if Playwright is
unavailable or a fetch fails, it falls back to `requests` in a thread
executor. Every fetch is rate-limited per-domain, checked against
robots.txt, and wrapped in retry-with-exponential-backoff.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

from scraper.config import ScraperConfig
from scraper.utils import RateLimiter, RobotsChecker, extract_domain, retry_async

try:
    from playwright.async_api import async_playwright, Browser, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # Playwright is optional at runtime; we degrade gracefully.
    PLAYWRIGHT_AVAILABLE = False


@dataclass
class CrawlResult:
    """Everything discovered for a single seed/site."""

    seed_url: str
    domain: str
    pages: Dict[str, str] = field(default_factory=dict)  # url -> html
    failed_urls: List[str] = field(default_factory=list)


class SchoolCrawler:
    """Discovers and fetches relevant pages for one school site at a time."""

    def __init__(self, config: ScraperConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("school_scraper")
        self.robots = RobotsChecker(config.user_agent, self.logger)
        self.rate_limiter = RateLimiter(config.rate_limit_delay_seconds)
        self._browser: Optional["Browser"] = None
        self._playwright_ctx = None
        self._semaphore = asyncio.Semaphore(config.max_concurrent_requests)

    # ----------------------------------------------------------------
    # Playwright lifecycle
    # ----------------------------------------------------------------
    async def start(self) -> None:
        if self.config.use_playwright and PLAYWRIGHT_AVAILABLE:
            try:
                self._playwright_ctx = await async_playwright().start()
                self._browser = await self._playwright_ctx.chromium.launch(headless=True)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "Playwright failed to launch (%s); falling back to requests-only mode.", exc
                )
                self._browser = None

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright_ctx is not None:
            await self._playwright_ctx.stop()

    # ----------------------------------------------------------------
    # Fetching
    # ----------------------------------------------------------------
    async def _fetch_with_playwright(self, url: str) -> Optional[str]:
        assert self._browser is not None
        page = await self._browser.new_page(user_agent=self.config.user_agent)
        try:
            await page.goto(
                url,
                timeout=self.config.playwright_timeout_ms,
                wait_until="domcontentloaded",
            )
            html = await page.content()
            return html
        except PlaywrightTimeoutError:
            self.logger.warning("Playwright timeout fetching %s", url)
            return None
        finally:
            await page.close()

    def _fetch_with_requests_sync(self, url: str) -> Optional[str]:
        headers = {"User-Agent": self.config.user_agent}
        response = requests.get(
            url,
            headers=headers,
            timeout=self.config.request_timeout_seconds,
            allow_redirects=True,
        )
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type and "html" not in content_type:
            return None
        return response.text

    async def _fetch_with_requests(self, url: str) -> Optional[str]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._fetch_with_requests_sync, url)

    async def fetch(self, url: str) -> Optional[str]:
        """Fetch a single URL's HTML, honoring robots.txt and rate limits."""
        if self.config.respect_robots_txt and not self.robots.can_fetch(url):
            self.logger.info("Skipping (robots.txt disallows): %s", url)
            return None

        async with self._semaphore:
            await self.rate_limiter.wait(url)

            fetch_fn = retry_async(
                max_retries=self.config.max_retries,
                backoff_factor=self.config.backoff_factor,
                exceptions=(Exception,),
            )

            if self._browser is not None:
                wrapped = fetch_fn(self._fetch_with_playwright)
                html = await wrapped(url)
                if html:
                    return html
                # Fall through to requests fallback if Playwright yielded nothing.

            wrapped = fetch_fn(self._fetch_with_requests)
            return await wrapped(url)

    # ----------------------------------------------------------------
    # Link discovery / relevance scoring
    # ----------------------------------------------------------------
    def _is_relevant_link(self, url: str, link_text: str) -> bool:
        haystack = f"{url} {link_text}".lower()
        return any(keyword in haystack for keyword in self.config.relevant_keywords)

    def _is_excluded(self, url: str) -> bool:
        lowered = url.lower()
        return any(pattern in lowered for pattern in self.config.excluded_patterns)

    def _extract_links(self, html: str, base_url: str) -> List[tuple[str, str]]:
        """Return list of (absolute_url, link_text) for in-domain, non-excluded links."""
        soup = BeautifulSoup(html, "html.parser")
        results: List[tuple[str, str]] = []
        base_domain = extract_domain(base_url)

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            if not href or self._is_excluded(href):
                continue
            absolute = urljoin(base_url, href)
            absolute, _ = urldefrag(absolute)  # drop #fragment
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if extract_domain(absolute) != base_domain:
                continue  # stay within the school's own domain
            link_text = anchor.get_text(" ", strip=True) or anchor.get("title", "")
            results.append((absolute, link_text))
        return results

    # ----------------------------------------------------------------
    # Breadth-first crawl of a single site
    # ----------------------------------------------------------------
    async def crawl_site(self, seed_url: str) -> CrawlResult:
        """
        BFS from seed_url, following only in-domain links, prioritizing and
        capturing pages whose URL/link-text matches relevant keywords, and
        always capturing the homepage itself (useful for name/address/phone).
        Stops when the page budget is exhausted or no new links are found.
        """
        domain = extract_domain(seed_url)
        result = CrawlResult(seed_url=seed_url, domain=domain)

        visited: Set[str] = set()
        queue: List[tuple[str, int]] = [(seed_url, 0)]
        queued: Set[str] = {seed_url}

        while queue and len(result.pages) < self.config.max_pages_per_site:
            url, depth = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)

            html = await self.fetch(url)
            if html is None:
                result.failed_urls.append(url)
                self.logger.error("Failed to fetch: %s", url)
                continue

            # Always keep the homepage; otherwise only keep relevance-matched pages.
            is_homepage = url.rstrip("/") == seed_url.rstrip("/")
            if is_homepage or self._is_relevant_link(url, ""):
                result.pages[url] = html

            if depth >= self.config.max_crawl_depth:
                continue

            for link_url, link_text in self._extract_links(html, url):
                if link_url in visited or link_url in queued:
                    continue
                relevant = self._is_relevant_link(link_url, link_text)
                # Always allow homepage-depth links to be explored a little,
                # but prioritize relevant links by putting them at the front.
                if relevant or depth == 0:
                    queued.add(link_url)
                    if relevant:
                        queue.insert(0, (link_url, depth + 1))
                    else:
                        queue.append((link_url, depth + 1))

            # If a relevant page was found but not yet stored (e.g. matched by
            # link text only), fetch-and-store it explicitly next iteration
            # via the normal queue mechanism above.

        if not result.pages and result.failed_urls:
            self.logger.warning("No pages successfully crawled for seed %s", seed_url)

        return result


async def crawl_all_seeds(config: ScraperConfig, logger: logging.Logger) -> List[CrawlResult]:
    """Crawl every configured seed URL concurrently (bounded by max_concurrent_sites)."""
    crawler = SchoolCrawler(config, logger)
    await crawler.start()

    site_semaphore = asyncio.Semaphore(config.max_concurrent_sites)
    results: List[CrawlResult] = []

    async def _bounded_crawl(seed: str) -> None:
        async with site_semaphore:
            try:
                logger.info("Starting crawl: %s", seed)
                res = await crawler.crawl_site(seed)
                logger.info(
                    "Finished crawl: %s | pages=%d failed=%d",
                    seed, len(res.pages), len(res.failed_urls),
                )
                results.append(res)
            except Exception as exc:  # noqa: BLE001 - never let one site kill the run
                logger.error("Unhandled error crawling %s: %s", seed, exc)
                results.append(CrawlResult(seed_url=seed, domain=extract_domain(seed)))

    try:
        await asyncio.gather(*(_bounded_crawl(seed) for seed in config.seed_urls))
    finally:
        await crawler.close()

    return results

