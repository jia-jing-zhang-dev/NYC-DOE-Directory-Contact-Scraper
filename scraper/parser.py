"""
parser.py
=========
Turns the raw HTML collected by the crawler into a structured SchoolRecord.

Extraction strategy
--------------------
1. Concatenate visible text from all crawled pages for a site.
2. Use regex to pull every email and phone number found anywhere.
3. For role-specific contacts (Principal, Assistant Principal, Parent
   Coordinator), scan text in small windows around role keywords to find
   the nearest associated name / email / phone ("proximity heuristic") --
   this mirrors how a human would skim a staff-directory page.
4. Pull school name from <title>/<h1>, address from a regex tuned to NYS
   street-address + ZIP patterns, and social links from anchor hrefs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from scraper.config import ScraperConfig
from scraper.crawler import CrawlResult
from scraper.utils import (
    clean_text,
    find_all_emails,
    find_all_phones,
    normalize_email,
    normalize_phone,
    standardize_address,
    strip_html,
)

ROLE_PRINCIPAL = "principal"
ROLE_ASSISTANT_PRINCIPAL = "assistant_principal"
ROLE_PARENT_COORDINATOR = "parent_coordinator"
ROLE_FAMILY_ENGAGEMENT = "family_engagement"

# Ordered so "assistant principal" / "vice principal" are checked before the
# bare "principal" keyword to avoid misclassification.
ROLE_KEYWORDS: Dict[str, List[str]] = {
    ROLE_PRINCIPAL: ["school leader", "principal"],
    ROLE_PARENT_COORDINATOR: ["parent coordinator", "family coordinator"],
    ROLE_FAMILY_ENGAGEMENT: ["family engagement", "family & community engagement", "parent engagement"],
}

_ADDRESS_RE = re.compile(
    r"\d{1,6}[-\s]?\d{0,4}\s+[A-Za-z0-9.'\s]{2,60}?"
    r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Lane|Ln|Place|Pl|"
    r"Court|Ct|Parkway|Pkwy|Square|Sq|Terrace|Ter|Expressway|Expy)\.?,?\s*"
    r"(?:[A-Za-z\s]+,)?\s*(?:NY|New York)\s*\d{5}(?:-\d{4})?",
    re.IGNORECASE,
)
_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_GRADES_RE = re.compile(
    r"\bGrades?\s*[:\-]?\s*(PK|Pre-?K|K|[0-9]{1,2})\s*(?:-|to|through)\s*(K|[0-9]{1,2})\b",
    re.IGNORECASE,
)
_DISTRICT_RE = re.compile(r"\bDistrict\s*#?\s*(\d{1,2})\b", re.IGNORECASE)
_DBN_RE = re.compile(r"\b(\d{2}[QqXxKkMmRr]\d{3})\b")  # NYC DOE District-Borough-Number, e.g. 30Q123


@dataclass
class SchoolRecord:
    """A single row of the final dataset (superset of required output columns)."""

    school_name: str = ""
    school_type: str = ""
    grades: str = ""
    borough: str = ""
    district: str = ""
    county: str = ""
    state: str = ""
    address: str = ""
    zip_code: str = ""
    phone_number: str = ""
    website: str = ""
    principal_name: str = ""
    principal_email: str = ""
    principal_phone: str = ""
    parent_coordinator_name: str = ""
    parent_coordinator_email: str = ""
    parent_coordinator_phone: str = ""
    family_engagement_contact: str = ""
    social_media_links: List[str] = field(default_factory=list)
    district_borough_number: str = ""
    source_url: str = ""
    last_crawled: str = ""
    pages_crawled: List[str] = field(default_factory=list)
    crawl_errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class SchoolPageParser:
    """Parses a CrawlResult into a SchoolRecord."""

    def __init__(self, config: ScraperConfig, logger: Optional[logging.Logger] = None) -> None:
        self.config = config
        self.logger = logger or logging.getLogger("school_scraper")

    # ------------------------------------------------------------------
    def parse(self, crawl_result: CrawlResult) -> SchoolRecord:
        record = SchoolRecord()
        record.website = crawl_result.seed_url
        record.source_url = crawl_result.seed_url
        record.borough = self.config.default_borough
        record.county = self.config.default_county
        record.state = self.config.default_state
        record.last_crawled = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        record.pages_crawled = list(crawl_result.pages.keys())
        record.crawl_errors = list(crawl_result.failed_urls)

        if not crawl_result.pages:
            record.school_name = crawl_result.domain
            return record

        soups: Dict[str, BeautifulSoup] = {
            url: BeautifulSoup(html, "html.parser") for url, html in crawl_result.pages.items()
        }

        # --- 新增的代码：将隐藏在 mailto 里的邮箱提取为可见文本 ---
        for soup in soups.values():
            # 找到所有包含 mailto: 的 a 标签
            for a_tag in soup.find_all("a", href=lambda href: href and href.lower().startswith("mailto:")):
                # 提取出干净的邮箱地址 (截掉前 7 个字符 "mailto:")
                hidden_email = a_tag["href"][7:].strip()
                # 把邮箱作为可见文本，强行追加到这个链接文字的后面
                a_tag.append(f" {hidden_email} ")
        # --------------------------------------------------------

        full_text = "\n".join(clean_text(soup.get_text(" ")) for soup in soups.values())
        full_text = full_text.replace(",", ", ")

        record.school_name = self._extract_school_name(soups, crawl_result.domain)
        record.school_type = self._extract_school_type(full_text)
        record.grades = self._extract_grades(full_text)
        record.district = self._extract_district(full_text)
        record.district_borough_number = self._extract_dbn(full_text)

        dbn = record.district_borough_number

        if dbn and len(dbn) >= 2:

            record.district = dbn[:2] 

        else:

            record.district = "Unknown"

        record.address, record.zip_code = self._extract_address(full_text)
        record.social_media_links = self._extract_social_links(soups)

        all_emails = find_all_emails(full_text)
        all_phones = find_all_phones(full_text)
        record.main_office_email = self._pick_main_office_email(all_emails)
        record.phone_number = all_phones[0] if all_phones else ""

        for role, keywords in ROLE_KEYWORDS.items():
            name, email, phone = self._extract_role_contact(full_text, keywords)
            if role == ROLE_PRINCIPAL:
                record.principal_name, record.principal_email, record.principal_phone = name, email, phone
            elif role == ROLE_PARENT_COORDINATOR:
                record.parent_coordinator_name = name
                record.parent_coordinator_email = email
                record.parent_coordinator_phone = phone
            elif role == ROLE_FAMILY_ENGAGEMENT:
                contact_bits = [b for b in (name, email, phone) if b]
                record.family_engagement_contact = " | ".join(contact_bits)

        return record

    # ------------------------------------------------------------------
    def _extract_school_name(self, soups: Dict[str, BeautifulSoup], fallback_domain: str) -> str:
        for soup in soups.values():
            h1 = soup.find("h1")
            if h1:
                text = clean_text(h1.get_text(" "))
                if text and len(text) < 120:
                    return text
        for soup in soups.values():
            if soup.title and soup.title.string:
                text = clean_text(soup.title.string)
                # Titles often look like "Contact Us | PS 123 Q" - take the longest segment.
                segments = [clean_text(s) for s in re.split(r"[|\-–]", text) if clean_text(s)]
                if segments:
                    return max(segments, key=len)
        return fallback_domain

    def _extract_school_type(self, text: str) -> str:
        lowered = text.lower()
        if "middle school" in lowered and "elementary" in lowered:
            return "PreK-8 / K-8"
        if "middle school" in lowered:
            return "Middle School"
        if "elementary" in lowered:
            return "Elementary School"
        if "pre-k" in lowered or "prek" in lowered or "pre-kindergarten" in lowered:
            return "PreK"
        return ""

    def _extract_grades(self, text: str) -> str:
        # 1. 强制认准 "Grades:" 冒号！精准提取截图里逗号分隔的格式 (如 PK,0K,01,02,SE)
        # 只允许提取 P, K, S, E, 数字, 逗号和横杠，这样碰到旁边的 Geographic 就会自动停下
        match = re.search(r"Grades?:\s*([PK0-9SE,\-]+(?:\s+[PK0-9SE,\-]+)*)", text)
        if match:
            return match.group(1).strip(',- ')
            
        # 2. 备用方案：如果有的学校用的是横杠格式 (比如 PreK-5 或 9-12)，依然强制认准冒号
        fallback = re.search(r"Grades?:\s*([A-Za-z0-9]+\s*-\s*[A-Za-z0-9]+)", text)
        if fallback:
            return fallback.group(1).strip()
            
        return ""

    def _extract_district(self, text: str) -> str:
        match = _DISTRICT_RE.search(text)
        return match.group(1) if match else ""

    def _extract_dbn(self, text: str) -> str:
        match = _DBN_RE.search(text)
        return match.group(1).upper() if match else ""

    def _extract_address(self, text: str) -> tuple[str, str]:
        match = _ADDRESS_RE.search(text)
        if not match:
            return "", ""
        raw_address = match.group(0)
        zip_match = _ZIP_RE.search(raw_address)
        zip_code = zip_match.group(0) if zip_match else ""
        # Strip the trailing ZIP from the street/city portion; it is returned
        # separately and re-combined by the exporter to avoid duplication.
        street_and_city = raw_address
        if zip_match:
            street_and_city = raw_address[: zip_match.start()].rstrip(", ")
        return standardize_address(street_and_city), zip_code

    def _extract_social_links(self, soups: Dict[str, BeautifulSoup]) -> List[str]:
        found: List[str] = []
        seen = set()
        for soup in soups.values():
            for anchor in soup.find_all("a", href=True):
                href = anchor["href"].strip()
                for domain in self.config.social_domains:
                    if domain in href.lower() and href not in seen:
                        seen.add(href)
                        found.append(href)
        return found

    def _pick_main_office_email(self, emails: List[str]) -> str:
        """Prefer generic-looking mailboxes (info@, office@, main@) over personal ones."""
        generic_prefixes = ("info", "office", "main", "contact", "frontdesk", "school")
        for email in emails:
            local_part = email.split("@")[0]
            if any(local_part.startswith(p) for p in generic_prefixes):
                return email
        return emails[0] if emails else ""

    def _extract_role_contact(self, text: str, keywords: List[str]) -> tuple[str, str, str]:
        """
        双轨制提取：保留完美的单人提取模式（给Principal），并新增独立的多人列表提取模式（给Parent Coordinator）。
        """
        all_names = []
        all_emails = []
        best_phone = ""
        
        lowered = text.lower()
        # 1. 提取邮箱和电话 (保持原样，这个一直很稳定)
        for keyword in keywords:
            start_search = 0
            while True:
                idx = lowered.find(keyword, start_search)
                if idx == -1:
                    break
                
                window = text[idx : idx + 250]
                emails_in_window = find_all_emails(window)
                for e in emails_in_window:
                    if e not in all_emails:
                        all_emails.append(e)
                
                phone = normalize_phone(window) or ""
                if phone and not best_phone:
                    best_phone = phone
                
                start_search = idx + len(keyword)

        # 辅助函数：手动将职位名称转换成大小写兼容模式，从而绝不使用 re.IGNORECASE！
        # 例如将 "principal" 变成 "[Pp][Rr][Ii][Nn][Cc][Ii][Pp][Aa][Ll]"
        def get_ci_kw(kw):
            return "".join([f"[{c.upper()}{c.lower()}]" if c.isalpha() else c for c in kw])

        # 2. 精准提取名字：执行双轨制
        for keyword in keywords:
            kw_pat = r"\b" + get_ci_kw(keyword) + r"s?\b"  # 支持复数 s
            
    # 标准人名定义：首字母大写的 2 到 3 个单词 (为了安全起见，这里去掉了外层的捕获括号)
            single_name = r"[A-Z][a-zA-Z\.\-']+(?:\s+[A-Z][a-zA-Z\.\-']+){1,2}"
            
            # 【轨道 A】：经典单人模式（之前抓 Principal 100% 成功的模式！）
            pat_single_1 = r"\b(" + single_name + r")[\s,;|:\-]+" + kw_pat
            pat_single_2 = kw_pat + r"[\s,;|:\-]+(" + single_name + r")"
            
            # 【轨道 B】：专门给 Parent Coordinator 的多人模式 (💥 解除封印版)
            # 允许用 and, &, 逗号 连接的多个人名（放宽到最多 15 个人！）
            sep = r"(?:[\s,;|&]+(?:and\s+)?)"
            multi_name = f"({single_name}(?:{sep}{single_name}){{0,15}})"
            
            pat_multi_1 = r"\b" + multi_name + r"[\s,;|:\-]+" + kw_pat
            pat_multi_2 = kw_pat + r"[\s,;|:\-]+" + multi_name

            # 将两条轨道的所有可能情况都扫一遍
            for pat in [pat_multi_1, pat_multi_2, pat_single_1, pat_single_2]:
                for match in re.finditer(pat, text):
                    raw_names = match.group(1)
                    
                    # 送去清洗器做最后的黑名单校验
                    valid_names_str = self._extract_name_near(raw_names + " ", keyword)
                    if valid_names_str:
                        for n in valid_names_str.split("; "):
                            if n and n not in all_names:
                                all_names.append(n)

        # 3. 极小窗口兜底（针对格式极其错乱的网页）
        if not all_names and keywords:
            for keyword in keywords:
                idx = lowered.find(keyword)
                if idx != -1:
                    tiny_window = text[max(0, idx - 60) : idx + 60]
                    fallback_names = self._extract_name_near(tiny_window, keyword)
                    if fallback_names:
                        all_names.extend(fallback_names.split("; "))

        unique_names = []
        for name in all_names:
            if name and name not in unique_names:
                unique_names.append(name)
        
        return "; ".join(unique_names), "; ".join(all_emails), best_phone


    def _extract_name_near(self, window: str, keyword: str) -> str:
        # 手动替换掉关键词，防止干扰
        def get_ci_kw(kw):
            return "".join([f"[{c.upper()}{c.lower()}]" if c.isalpha() else c for c in kw])
        kw_pat_ci = r"\b" + get_ci_kw(keyword) + r"s?\b"
        without_keyword = re.sub(kw_pat_ci, " ", window)
        
        # 严格要求大写的正则
        name_pattern = re.compile(r"\b([A-Z][a-zA-Z\.\-']+(?:\s+[A-Z][a-zA-Z\.\-']+){1,2})\b")
        
        # 最强黑名单，已拉黑之前截图中的所有菜单栏单词
        blacklist = {
            "school", "team", "election", "panel", "resolution", "parent", 
            "fundraiser", "frequently", "role", "all", "sexual", "coordinat", 
            "space", "district", "number", "family", "worker", "counselor", 
            "education", "helpful", "campa", "harassment", "public", "new", 
            "york", "department", "board", "committee", "community", "council", 
            "safety", "health", "wellness", "policy", "student", "teacher", 
            "staff", "faculty", "leader", "leadership", "overview", "quality", 
            "reports", "accessibility", "geographic", "borough", "contact", 
            "information", "report", "bullying", "share", "building",
            "meeting", "bylaws", "declaration", "schedule", "special", "plans",
            "campaign", "appointee", "seats", "application", "resources", "responsib",
            "training", "conference", "emergency", "annual", "survey",
            "teachhub", "service", "charter", "plant", "powered", "food", "menus",
            "facilities", "testing", "avenue", "water", "elections", "councils", "services", "brea"
        }
        
        found_names = []
        for match in name_pattern.finditer(without_keyword):
            candidate = clean_text(match.group(1))
            
            # 双保险：强制校验每一个词是否真正是大写开头
            words = candidate.split()
            if not all(w[0].isupper() for w in words if w):
                continue
                
            lowered_candidate = candidate.lower()
            if not any(bad_word in lowered_candidate.split() for bad_word in blacklist):
                if candidate not in found_names:
                    found_names.append(candidate)
                    
        return "; ".join(found_names)