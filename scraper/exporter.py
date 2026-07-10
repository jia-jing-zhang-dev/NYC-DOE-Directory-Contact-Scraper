"""
exporter.py
===========
Exports cleaned SchoolRecords to Excel (.xlsx), CSV, and JSON using the
exact output column order specified by the project requirements.
"""

from __future__ import annotations

import json
import logging
import csv 
from pathlib import Path
from typing import List, Optional

from scraper.config import OUTPUT_COLUMNS
from scraper.parser import SchoolRecord



def _record_to_row(record: SchoolRecord, role: str, first_name: str, last_name: str, email: str) -> dict:
    """复刻目标格式的单行映射"""
    return {
        "Contacted Principal?": "",  # 留空，方便你在 Excel 里勾选
        "District": record.district_borough_number[:2], # 从 DBN 自动提取
        "Role": role,                # "Principal" 或 "Parent Coordinator"
        "First Name": first_name,
        "Last Name": last_name,
        "Email": email,
        "Phone Number": record.phone_number,
        "Email of Contactor": "",    # 留空
        "School Address": record.address,
        "District Borough Number": record.district_borough_number,
        "Source URL": record.source_url,
        "Last Crawled": record.last_crawled,

        "School Name": record.school_name,
        "Borough": record.borough,
        "Grades": record.grades,


    }


class DataExporter:
    def __init__(self, output_dir: Path, basename: str, logger: Optional[logging.Logger] = None) -> None:
        self.output_dir = output_dir
        self.basename = basename
        self.logger = logger or logging.getLogger("school_scraper")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def append_to_csv(self, row_data: dict) -> None:
        # 1. 质量过滤：这里也要做相应的调整，从字典中获取名字
        invalid_keywords = ["404", "Not Found", "Page Not Found"]
        school_name = row_data.get("School Name", "") # 从字典获取
        
        if any(keyword in school_name for keyword in invalid_keywords):
            self.logger.warning(f"检测到无效记录，已跳过: {school_name}")
            return

        # 2. 正常保存逻辑
        path = self.output_dir / f"{self.basename}.csv"
        # row 变量现在就是你传进来的 row_data
        file_exists = path.exists()

        with path.open("a", newline="", encoding="utf-8-sig") as f:
            # fieldnames 直接用字典的键
            writer = csv.DictWriter(f, fieldnames=row_data.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(row_data) # 写入字典
        
        self.logger.info(f"成功追加记录到 CSV: {school_name}")


