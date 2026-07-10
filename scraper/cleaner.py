"""
cleaner.py
==========
Post-processing pass over parsed SchoolRecords:

* Trim whitespace / strip stray HTML on every text field.
* Validate emails; drop anything malformed.
* Normalize phone numbers to a single format.
* Standardize addresses.
* Deduplicate emails/phones within a record's social/contact fields.
* Detect and merge duplicate school records (same domain or same
  normalized name + address).
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from scraper.parser import SchoolRecord
from scraper.utils import (
    clean_text,
    extract_domain,
    is_valid_email,
    normalize_phone,
    standardize_address,
    strip_html,
)


class DataCleaner:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self.logger = logger or logging.getLogger("school_scraper")

    # ------------------------------------------------------------------
    def clean_records(self, records: List[SchoolRecord]) -> List[SchoolRecord]:
        cleaned = [self._clean_record(r) for r in records]
        deduped = self._deduplicate(cleaned)
        self.logger.info(
            "Cleaning complete: %d records in, %d unique records out", len(records), len(deduped)
        )
        return deduped

    # ------------------------------------------------------------------
    def _clean_record(self, record: SchoolRecord) -> SchoolRecord:
        record.school_name = clean_text(strip_html(record.school_name))
        record.school_type = clean_text(record.school_type)
        record.grades = clean_text(record.grades)
        record.borough = clean_text(record.borough)
        record.district = clean_text(record.district)
        record.county = clean_text(record.county)
        record.state = clean_text(record.state)
        record.address = standardize_address(record.address)
        record.zip_code = clean_text(record.zip_code)

        record.phone_number = self._clean_phone(record.phone_number)
        record.principal_phone = self._clean_phone(record.principal_phone)
        record.parent_coordinator_phone = self._clean_phone(record.parent_coordinator_phone)

        record.principal_email = self._clean_email(record.principal_email)
        record.parent_coordinator_email = self._clean_email(record.parent_coordinator_email)

        record.principal_name = clean_text(strip_html(record.principal_name))
        record.parent_coordinator_name = clean_text(strip_html(record.parent_coordinator_name))
        record.family_engagement_contact = clean_text(strip_html(record.family_engagement_contact))

        # De-duplicate social links while preserving order.
        seen = set()
        unique_links = []
        for link in record.social_media_links:
            link = link.strip()
            if link and link not in seen:
                seen.add(link)
                unique_links.append(link)
        record.social_media_links = unique_links

        record.district_borough_number = clean_text(record.district_borough_number).upper()
        return record

    @staticmethod
    def _clean_phone(raw: str) -> str:
        if not raw:
            return ""
        normalized = normalize_phone(raw)
        return normalized or ""

    @staticmethod
    def _clean_email(raw: str) -> str:
        if not raw:
            return ""
        # 支持用逗号分隔的多个邮箱：拆分 -> 逐个验证 -> 重新拼装
        valid_emails = []
        for part in str(raw).split(","):
            candidate = clean_text(part).lower()
            if is_valid_email(candidate):
                valid_emails.append(candidate)
        
        return ", ".join(valid_emails)
    # ------------------------------------------------------------------
    def _deduplicate(self, records: List[SchoolRecord]) -> List[SchoolRecord]:
        """
        Merge records that clearly refer to the same school: identical
        website domain, OR identical normalized (name, zip) pair.
        The record with more populated fields "wins" and absorbs any
        missing fields from its duplicate.
        """
        by_key: Dict[str, SchoolRecord] = {}
        order: List[str] = []

        for record in records:
            domain_key = extract_domain(record.website)
            name_key = f"{record.school_name.strip().lower()}|{record.zip_code.strip()}"
            key = domain_key or name_key

            if key in by_key:
                merged = self._merge(by_key[key], record)
                by_key[key] = merged
                self.logger.info("Merged duplicate school record for key=%s", key)
            else:
                by_key[key] = record
                order.append(key)

        return [by_key[k] for k in order]

    @staticmethod
    def _merge(primary: SchoolRecord, secondary: SchoolRecord) -> SchoolRecord:
        """Fill any blank field on `primary` using `secondary`'s value."""
        for field_name, value in secondary.as_dict().items():
            if field_name in ("social_media_links", "pages_crawled", "crawl_errors"):
                continue
            current = getattr(primary, field_name)
            if not current and value:
                setattr(primary, field_name, value)
        primary.social_media_links = sorted(
            set(primary.social_media_links) | set(secondary.social_media_links)
        )
        primary.pages_crawled = sorted(set(primary.pages_crawled) | set(secondary.pages_crawled))
        primary.crawl_errors = sorted(set(primary.crawl_errors) | set(secondary.crawl_errors))
        return primary


def split_name(name: str) -> tuple[str, str]:
    name = clean_name(name)
    parts = name.split()

    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    elif len(parts) == 1:
        return parts[0], ""
    else:
        return "", ""