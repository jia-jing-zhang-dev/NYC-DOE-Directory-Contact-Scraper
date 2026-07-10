# Queens PreK–8 School Contact Scraper

A production-quality, polite, asynchronous web scraper that collects
**publicly available** contact information for preK–8 schools in Queens,
New York City, starting only from a list of **seed URLs** (school
homepages or official education-directory pages).

It automatically discovers relevant internal pages — Contact, Staff
Directory, Administration, Faculty, Leadership, Parent Coordinator, Family
Engagement, About — by following internal links, so you never have to
enumerate every page yourself.

> **Scope & intent:** This tool only crawls official school websites /
> official education directories that you supply as seed URLs, respects
> `robots.txt`, and rate-limits requests. It collects information school
> administrations already publish for parents and the public (names,
> office emails/phones, addresses). It does not bypass logins, scrape
> personal social media profiles, or harvest non-public data.

---

## Features

- **Automatic page discovery** — BFS crawl from each seed URL, following
  only same-domain links, prioritizing pages matching keywords like
  `contact`, `staff`, `administration`, `faculty`, `leadership`,
  `parent coordinator`, `family engagement`, `about`.
- **Playwright-first fetching** with automatic fallback to `requests` if
  Playwright isn't installed or a page fails to render.
- **Politeness**: per-domain rate limiting, `robots.txt` compliance,
  configurable concurrency caps, retry with exponential backoff.
- **Structured extraction**: school name, type, grades, borough, district,
  county, state, address, ZIP, phone, main office email, principal,
  assistant principal, parent coordinator, family engagement contact,
  social media links.
- **Data cleaning**: HTML stripped, whitespace trimmed, phone numbers
  normalized to `(XXX) XXX-XXXX`, emails validated and lower-cased,
  addresses standardized, duplicate schools merged.
- **Multi-format export**: Excel (`.xlsx`, styled header + auto-width),
  CSV, and JSON (full-fidelity, including internal crawl metadata).
- **Resilient**: one failing school never stops the batch; every failure
  is logged to `logs/errors.log`.
- **Progress bars** via `tqdm`; structured logging to console + file.

---

## Project Structure

```
nyc_school_scraper/
├── scraper/
│   ├── __init__.py
│   ├── config.py      # Central typed configuration
│   ├── utils.py        # Logging, retry/backoff, normalization, robots.txt, rate limiter
│   ├── crawler.py      # Async link-discovery crawler (Playwright + requests)
│   ├── parser.py       # HTML -> SchoolRecord field extraction
│   ├── cleaner.py       # Cleaning, validation, deduplication
│   └── exporter.py      # xlsx / csv / json export
├── data/                 # Intermediate/raw data (gitignored)
├── logs/                 # scraper.log, errors.log
├── output/                # Final exported datasets
├── main.py               # CLI entry point
├── requirements.txt
├── seeds.example.txt
└── README.md
```

---

## Installation

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium        # one-time browser download
```

---

## Usage

### 1. Provide seed URLs directly

```bash
python main.py --seed-urls https://schoolsearch.schools.nyc/We
```

### 2. Or provide a seed file (one URL per line)

```bash
cp seeds.example.txt seeds.txt
# edit seeds.txt with real official school URLs
python main.py --seed-file seeds.txt
```

### Useful flags

| Flag | Default | Description |
|---|---|---|
| `--output-dir` | `output/` | Where `.xlsx`/`.csv`/`.json` are written |
| `--max-pages` | `40` | Max pages crawled per school site |
| `--max-depth` | `3` | Max link-following depth |
| `--concurrency` | `5` | Concurrent requests per site |
| `--max-sites` | `3` | School sites crawled in parallel |
| `--rate-limit` | `1.0` | Seconds between requests to the same domain |
| `--max-retries` | `3` | Retries per failed request (exponential backoff) |
| `--no-playwright` | off | Use `requests`-only fetching |
| `--ignore-robots` | off | **Not recommended** — disables robots.txt checks |
| `--log-level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

Outputs are written to `output/queens_prek8_schools.{xlsx,csv,json}` by
default (override with `--output-basename`).

---

## Output Columns

```
School Name | District | Borough | County | State | Grades | Principal |
Principal Email | Principal Phone Number | Assistant Principal |
Assistant Principal Email | Assistant Principal Phone Number |
Parent Coordinator | Parent Coordinator Email |
Parent Coordinator Phone Number | Main Office Email | School Address |
District Borough Number | Source URL | Last Crawled
```

The JSON export additionally includes a `_raw` object per record with
full internal fields (e.g. `pages_crawled`, `crawl_errors`,
`social_media_links`) for downstream reuse.

---

## Notes on data quality

- Fields not published on a school's own site (e.g. `District`,
  `County`) fall back to sensible defaults (`Queens`, `New York`) or are
  left blank rather than guessed — cross-reference against the official
  [NYC DOE school directory](https://www.schools.nyc.gov) for anything
  left blank.
- Principal / Assistant Principal / Parent Coordinator extraction uses a
  proximity heuristic (nearest name/email/phone to each role keyword) and
  should be spot-checked, as staff pages vary widely in structure.
- Re-running the scraper against the same seeds will safely overwrite the
  previous export; duplicate schools (same domain, or same name+ZIP) are
  merged automatically.

---

## Extending

- Add new page keywords in `scraper/config.py::DEFAULT_RELEVANT_KEYWORDS`.
- Add new extraction fields by extending `SchoolRecord` in
  `scraper/parser.py` and the column mapping in
  `scraper/exporter.py::_record_to_row`.
- Swap in a different jurisdiction (borough/county) by passing different
  `ScraperConfig` defaults — nothing else needs to change.

---

## License

Provided as-is for building a public-interest school-contact dataset from
sources schools themselves have published for parents and the public.
Always review each site's terms of use and `robots.txt` before crawling
at scale.
