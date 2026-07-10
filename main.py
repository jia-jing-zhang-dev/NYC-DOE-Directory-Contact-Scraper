#!/usr/bin/env python3
"""
main.py
=======
CLI entry point for the Queens preK-8 School Contact Scraper.

Usage
-----
    python main.py --seed-urls https://www.ps123q.org https://www.is456q.org
    python main.py --seed-file seeds.txt --max-pages 30 --no-playwright
    python main.py --seed-urls https://example-school.org --output-dir ./output

The user only needs to supply seed URLs (one school homepage or official
directory page per school). The crawler automatically discovers Contact,
Staff Directory, Administration, Faculty, Leadership, Parent Coordinator,
Family Engagement, and About pages by following internal links.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List

from tqdm import tqdm
import re 

from scraper.cleaner import DataCleaner
from scraper.config import LOG_DIR, OUTPUT_DIR, ScraperConfig
from scraper.crawler import crawl_all_seeds
from scraper.exporter import DataExporter, _record_to_row  # 确保这里导入了 _record_to_row
from scraper.parser import SchoolPageParser, SchoolRecord
from scraper.utils import setup_logging, clean_name        # 假设你把 clean_name 放在了 utils.py

def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Scrape publicly available contact info for Queens, NYC preK-8 schools "
        "from official school websites, starting from seed URLs."
    )
    seed_group = parser.add_mutually_exclusive_group(required=True)
    seed_group.add_argument(
        "--seed-urls", nargs="+", metavar="URL",
        help="One or more school homepage / official directory URLs.",
    )
    seed_group.add_argument(
        "--seed-file", type=Path, metavar="PATH",
        help="Path to a text file with one seed URL per line.",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Directory for exported files.")
    parser.add_argument("--output-basename", type=str, default="queens_prek8_schools")
    parser.add_argument("--max-pages", type=int, default=1, help="Max pages crawled per school site.")
    parser.add_argument("--max-depth", type=int, default=0, help="Max link-following depth per site.")
    parser.add_argument("--concurrency", type=int, default=5, help="Max concurrent requests per site.")
    parser.add_argument("--max-sites", type=int, default=3, help="Max school sites crawled in parallel.")
    parser.add_argument("--rate-limit", type=float, default=1.0, help="Seconds between requests to the same domain.")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per failed request.")
    parser.add_argument("--no-playwright", action="store_true", help="Disable Playwright; use requests only.")
    parser.add_argument("--ignore-robots", action="store_true", help="Do not honor robots.txt (not recommended).")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args(argv)


def load_seed_urls(args: argparse.Namespace) -> List[str]:
    if args.seed_urls:
        return [u.strip() for u in args.seed_urls if u.strip()]
    text = args.seed_file.read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]



async def run(config: ScraperConfig) -> List[SchoolRecord]:
    logger = setup_logging(config.log_dir, config.log_level)
    exporter = DataExporter(config.output_dir, config.output_basename, logger)
    parser = SchoolPageParser(config, logger)
    records: List[SchoolRecord] = []

    IGNORE_TITLES = {
        'principal', 'co-principal', 'assistant principal', 'parent coordinator',

        'school worker', 'acting principal', 'interim principal', 'teacher',

        'staff', 'director', 'coordinator', 'superintendent', 'president',

         'vice principal', 'ap', 'ia'    }

    crawl_results = await crawl_all_seeds(config, logger)

    def process_contacts(record, name_raw, email_raw, role_title):
        rows = []

        if not name_raw and not email_raw:
            return rows

        if name_raw:
            name_raw = name_raw.replace("&nbsp;", " ")

        raw_names = re.split(r"[;|\n,/]+", name_raw) if name_raw else []
        raw_emails = re.split(r"[;|\n\s,]+", email_raw) if email_raw else []

        valid_names = []
        for n in raw_names:
            n_clean = re.sub(r"\s+", " ", n).strip()

            if not n_clean or len(n_clean) < 2:
                continue

            if n_clean.lower() in IGNORE_TITLES:
                continue

            valid_names.append(n_clean)

        valid_emails = []
        seen = set()

        for e in raw_emails:
            e_clean = e.strip()

            if (
                e_clean
                and "@" in e_clean
                and e_clean not in seen
            ):
                seen.add(e_clean)
                valid_emails.append(e_clean)

        if valid_names:
            max_count = min(10, len(valid_names))
        elif valid_emails:
            max_count = 1
        else:
            max_count = 0

        for i in range(max_count):

            current_name = valid_names[i] if i < len(valid_names) else ""
            current_email = valid_emails[i] if i < len(valid_emails) else ""

            if not current_name and not current_email:
                continue

            first, middle, last = split_name(current_name)

            if is_fake_name(first, middle, last):
                continue

            row = _record_to_row(
                record,
                role_title,
                first,
                last,
                current_email,
            )

            rows.append(row)

        return rows

    for result in tqdm(crawl_results, desc="Processing sites", unit="site"):
        try:

            record = parser.parse(result)
            records.append(record)

            rows = []

            rows.extend(
                process_contacts(
                    record,
                    record.principal_name,
                    record.principal_email,
                    "Principal",
                )
            )

            rows.extend(
                process_contacts(
                    record,
                    record.parent_coordinator_name,
                    record.parent_coordinator_email,
                    "Parent Coordinator",
                )
            )

            # ========= 合并重复联系人 =========
            merged = {}

            for row in rows:

                first = row["First Name"].strip().lower()
                last = row["Last Name"].strip().lower()
                email = row["Email"].strip().lower()

                # 如果没有名字，用 email 区分
                if first or last:
                    key = (first, last)
                elif email:
                    key = ("email", email)
                else:
                    # 没名字没邮箱，不合并
                    key = id(row)

                if key not in merged:
                    merged[key] = row

                else:
                    old_role = merged[key]["Role"]
                    new_role = row["Role"]

                    if new_role not in old_role:
                        merged[key]["Role"] = (
                            old_role + " + " + new_role
                        )

                    if not merged[key]["Email"] and row["Email"]:
                        merged[key]["Email"] = row["Email"]

            for row in merged.values():
                exporter.append_to_csv(row)

        except Exception as exc:
            logger.error(
                "Failed to process %s: %s",
                result.seed_url,
                exc,
            )

    return records

def is_fake_name(first, middle, last):
    # 先处理掉名字中的点号
    f = first.replace(".", "")
    l = last.replace(".", "")

    # 判断 first 和 last 是否都只有 1 个字母
    if len(f) == 1 and len(l) == 1:
        return True

    return False

def split_name(name: str) -> tuple[str, str, str]:
    name = clean_name(name)
    parts = name.split()

    suffixes = {"jr", "sr", "ii", "iii", "iv"}

    # 去掉末尾的 suffix
    while parts and parts[-1].lower().rstrip(".,") in suffixes:
        parts.pop()

    if len(parts) >= 3:
        first = parts[0]
        middle = " ".join(parts[1:-1])
        last = parts[-1]
    elif len(parts) == 2:
        first = parts[0]
        middle = ""
        last = parts[1]
    elif len(parts) == 1:
        first = parts[0]
        middle = ""
        last = ""
    else:
        first = middle = last = ""

    return first, middle, last
    
def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    seed_urls = load_seed_urls(args)

    if not seed_urls:
        print("No seed URLs provided.", file=sys.stderr)
        return 1

    config = ScraperConfig(
        seed_urls=seed_urls,
        max_pages_per_site=args.max_pages,
        max_crawl_depth=args.max_depth,
        max_concurrent_requests=args.concurrency,
        max_concurrent_sites=args.max_sites,
        rate_limit_delay_seconds=1.0,
        max_retries=args.max_retries,
        use_playwright=not args.no_playwright,
        respect_robots_txt=not args.ignore_robots,
        output_dir=args.output_dir,
        output_basename=args.output_basename,
        log_dir=LOG_DIR,
        log_level=args.log_level,
    )

    records = asyncio.run(run(config))
    print(f"\nDone. {len(records)} school record(s) written to {config.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())