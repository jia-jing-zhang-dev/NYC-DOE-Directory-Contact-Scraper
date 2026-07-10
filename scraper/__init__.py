"""
NYC PreK-8 School Contact Scraper
==================================

A production-grade, polite, asyncio-based web scraper for collecting
publicly available contact information from official preK-8 school
websites and official education directories in Queens, New York City.

Modules
-------
config.py    - Central configuration (dataclasses, CLI-tunable settings).
utils.py     - Logging, retry/backoff, normalization, robots.txt, rate limiting.
crawler.py   - Async link-discovery crawler (Playwright + requests fallback).
parser.py    - HTML -> structured SchoolRecord extraction.
cleaner.py   - Deduplication and field validation/cleaning.
exporter.py  - Excel / CSV / JSON export in the required column order.
"""

__version__ = "1.0.0"
