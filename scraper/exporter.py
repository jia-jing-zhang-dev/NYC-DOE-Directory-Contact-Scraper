"""
exporter.py
===========
Exports cleaned SchoolRecords to Excel (.xlsx), CSV, and JSON.
"""

from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import List, Optional

from scraper.config import OUTPUT_COLUMNS
from scraper.parser import SchoolRecord


# ------------------------------------------------------------------
# Email normalization
# ------------------------------------------------------------------

def normalize_export_email(email: str) -> str:
    if not email:
        return ""

    email = email.strip().lower()

    username, sep, domain = email.rpartition("@")

    if not sep:
        return email

    if domain in {
        "schools.ny",
        "schools.nyc",
        "schools.nyc.g",
        "schools.nyc.go",
        "schools.nyc.gov",
    }:
        return f"{username}@schools.nyc.gov"

    return email

# ------------------------------------------------------------------
# Borough extraction
# ------------------------------------------------------------------

def extract_borough_from_address(address: str) -> str:
    if not address:
        return ""

    parts = [part.strip() for part in address.split(",")]

    if len(parts) < 2:
        return ""

    borough = parts[-2]

    borough_map = {
        "Brooklyn": "Brooklyn",
        "Bronx": "Bronx",
        "New York": "Manhattan",
        "Manhattan": "Manhattan",
        "Queens": "Queens",
        "Staten Island": "Staten Island",
    }

    return borough_map.get(borough, borough)


# ------------------------------------------------------------------
# Convert SchoolRecord to output row
# ------------------------------------------------------------------

def _record_to_row(
    record: SchoolRecord,
    role: str,
    first_name: str,
    last_name: str,
    email: str,
) -> dict:

    email = normalize_export_email(email)

    borough = extract_borough_from_address(record.address)

    return {
        "Contacted Principal?": "",
        "District": record.district_borough_number[:2],
        "Role": role,
        "First Name": first_name,
        "Last Name": last_name,
        "Email": email,
        "Phone Number": record.phone_number,
        "Email of Contactor": "",
        "School Address": record.address,
        "District Borough Number": record.district_borough_number,
        "Source URL": record.source_url,
        "Last Crawled": record.last_crawled,
        "School Name": record.school_name,
        "Borough": borough,
        "Grades": record.grades,
    }


# ------------------------------------------------------------------
# DataExporter
# ------------------------------------------------------------------

class DataExporter:

    def __init__(
        self,
        output_dir: Path,
        basename: str,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.output_dir = output_dir
        self.basename = basename
        self.logger = logger or logging.getLogger("school_scraper")

        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def clear_csv(self) -> None:
        """Delete the previous CSV before starting a new crawl."""

        path = self.output_dir / f"{self.basename}.csv"

        if path.exists():
            path.unlink()
            self.logger.info(f"已清空旧 CSV: {path}")

    # ------------------------------------------------------------------
    def append_to_csv(self, row_data: dict) -> None:

        invalid_keywords = [
            "404",
            "Not Found",
            "Page Not Found",
        ]

        school_name = row_data.get("School Name", "")

        if any(keyword.lower() in school_name.lower()
            for keyword in invalid_keywords):
            self.logger.warning(
                f"Invalid record detected, skipped.: {school_name}"
            )
            return

        path = self.output_dir / f"{self.basename}.csv"

        file_exists = path.exists()

        with path.open(
            "a",
            newline="",
            encoding="utf-8-sig",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=OUTPUT_COLUMNS,
                extrasaction="ignore",
            )

            if not file_exists:
                writer.writeheader()

            writer.writerow(row_data)

        self.logger.info(
            f"Successfully appended record to CSV: {school_name}"
        )