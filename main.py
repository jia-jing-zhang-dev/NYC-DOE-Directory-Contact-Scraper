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
    # 1. 初始化
    logger = setup_logging(config.log_dir, config.log_level)
    exporter = DataExporter(config.output_dir, config.output_basename, logger)
    parser = SchoolPageParser(config, logger)
    records: List[SchoolRecord] = []

    # 定义需要被忽略的头衔关键词（转小写），避免将头衔当成名字输出，避免姓名与邮箱错位
    IGNORE_TITLES = {
        'principal', 'co-principal', 'assistant principal', 'parent coordinator', 
        'school worker', 'acting principal', 'interim principal', 'teacher', 
        'staff', 'director', 'coordinator', 'superintendent', 'president',
        'vice principal', 'ap', 'ia'
    }

    # 2. 爬取所有种子
    crawl_results = await crawl_all_seeds(config, logger)

    # 3. 循环处理数据：每查完一个学校，立即处理并存入 CSV
    for result in tqdm(crawl_results, desc="Processing sites", unit="site"):
        try:
            record = parser.parse(result)
            records.append(record)
            
            # --- 统一定义一个处理多人的内部函数 ---
# --- 统一定义一个处理多人的内部函数 ---
            def process_contacts(name_raw, email_raw, role_title):
                if not name_raw and not email_raw:
                    return
                
                # 如果有 HTML 的无间断空格，先替换掉
                if name_raw:
                    name_raw = name_raw.replace('&nbsp;', ' ')
                
                raw_names = re.split(r'[;|\n,/]+', name_raw) if name_raw else []
                raw_emails = re.split(r'[;|\n\s,]+', email_raw) if email_raw else []
                
                valid_names = []
                for n in raw_names:
                    # 强力清理所有多余空格和不可见字符
                    n_clean = re.sub(r'\s+', ' ', n).strip()
                    if not n_clean or len(n_clean) < 2:
                        continue
                        
                    # 强制全小写后对比，彻底拦截 "school worker" 和 "principal"
                    if n_clean.lower() in IGNORE_TITLES:
                        continue
                        
                    # 直接加入有效名单，跳过可能有 Bug 的 clean_name
                    valid_names.append(n_clean)
                
                valid_emails = []
                for e in raw_emails:
                    e_clean = e.strip()
                    if e_clean and '@' in e_clean and e_clean not in valid_emails:
                        valid_emails.append(e_clean)
                
            # 5. 完美对齐合并：以名字的数量为主导！
                if valid_names:
                    # 如果有名字，严格按照名字的数量建行。多抓到的无关邮箱统统丢弃！
                    max_count = min(10, len(valid_names))
                elif valid_emails:
                    # 如果网页上真的没写名字，只有邮箱，那最多只建 1 行
                    max_count = 1
                else:
                    max_count = 0                
                for i in range(max_count):
                    current_name = valid_names[i] if i < len(valid_names) else ""
                    current_email = valid_emails[i] if i < len(valid_emails) else ""
                    
                    if not current_name and not current_email:
                        continue
                        
                    parts = current_name.split()
                    first = parts[0] if parts else ""
                    if len(parts) > 1:
                        if parts[-1] == "Jr":
                            last = parts[-2]
                        else:
                            last = parts[-1]
                    else:
                        last = ""                        
                    
                    row = _record_to_row(record, role_title, first, last, current_email)
                    exporter.append_to_csv(row)
            # --- 调用该函数处理校长和家委会成员 ---
            process_contacts(record.principal_name, record.principal_email, "Principal")
            process_contacts(record.parent_coordinator_name, record.parent_coordinator_email, "Parent Coordinator")
                
        except Exception as exc:
            logger.error("Failed to process %s: %s", result.seed_url, exc)

    return records

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