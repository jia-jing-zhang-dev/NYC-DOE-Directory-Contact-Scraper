"""
config.py
=========
Central, typed configuration for the scraper. All tunable knobs live here
so the rest of the codebase never hard-codes magic numbers or strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
LOG_DIR = PROJECT_ROOT / "logs"
OUTPUT_DIR = PROJECT_ROOT / "output"

for _dir in (DATA_DIR, LOG_DIR, OUTPUT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Keywords used to identify "relevant" internal pages worth crawling/parsing.
# Matched case-insensitively against link text, URL path, and page <title>.
# --------------------------------------------------------------------------
DEFAULT_RELEVANT_KEYWORDS: List[str] = [
    "contact",
    "contact-us",
    "staff",
    "staff-directory",
    "directory",
    "administration",
    "faculty",
    "leadership",
    "parent-coordinator",
    "parent coordinator",
    "family-engagement",
    "family engagement",
    "about",
    "about-us",
    "our-school",
    "meet-the-principal",
    "principal",
]

# Links containing these substrings are never followed (noise / non-content).
DEFAULT_EXCLUDED_PATTERNS: List[str] = [
    "javascript:", "mailto:", "tel:", "#", ".pdf", ".jpg", ".png",
    "/wp-admin", "/wp-json", "logout", "login",
    # 新增以下屏蔽规则：
    "/about-us/messages-for-families/", 
    "/about-us/news/", 
    "/about-us/reports/",
    "/school-life/",
]

SOCIAL_DOMAINS: List[str] = [
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "linkedin.com",
]


@dataclass
class ScraperConfig:
    """All runtime configuration for a single scrape run."""
    seed_urls: List[str]
    allowed_domains: List[str] = field(default_factory=list)

    # --- Crawl limits ---
    max_pages_per_site: int = 1
    max_crawl_depth: int = 0
    max_concurrent_requests: int = 15  # 确保这里有值
    max_concurrent_sites: int = 5      # 确保这里有值

    # --- Networking ---
    request_timeout_seconds: int = 10
    rate_limit_delay_seconds: float = 1.0  # <--- 如果这一行报错，请检查是否拼写完全一致！
    max_retries: int = 1
    backoff_factor: float = 0.5
    user_agent: str = "QueensSchoolDirectoryBot/1.0"  # <--- 就是缺了这一行！
    # ... 其余代码 ...
    # --- Behavior --------------------------------------------------------------
    respect_robots_txt: bool = True
    use_playwright: bool = False
    playwright_timeout_ms: int = 20000

    # --- Content classification -------------------------------------------------
    relevant_keywords: List[str] = field(default_factory=lambda: list(DEFAULT_RELEVANT_KEYWORDS))
    excluded_patterns: List[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDED_PATTERNS))
    social_domains: List[str] = field(default_factory=lambda: list(SOCIAL_DOMAINS))

    # --- Static jurisdiction defaults for this dataset (Queens, NYC preK-8) ----
    default_borough: str = "Queens"
    default_county: str = "Queens"
    default_state: str = "New York"

    # --- Output ------------------------------------------------------------------
    output_dir: Path = OUTPUT_DIR
    data_dir: Path = DATA_DIR
    log_dir: Path = LOG_DIR
    log_level: str = "INFO"
    output_basename: str = "queens_prek8_schools"

    def __post_init__(self) -> None:
        if not self.allowed_domains:
            from scraper.utils import extract_domain

            self.allowed_domains = sorted(
                {extract_domain(url) for url in self.seed_urls if url}
            )


# Required, ordered output columns for every export format.
OUTPUT_COLUMNS: List[str] = [
    "School Name",
    "District",
    "Borough",
    "County",
    "State",
    "Grades",
    "Principal",
    "Principal Email",
    "Parent Coordinator",
    "Parent Coordinator Email",
    "School Phone Number",  # <--- 新增这一行！
    "School Address",
    "District Borough Number",
    "Source URL",
    "Last Crawled",
]
