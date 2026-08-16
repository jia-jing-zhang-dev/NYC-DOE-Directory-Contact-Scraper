NYC DOE Directory Contact Scraper

An asynchronous Python web scraper for collecting publicly available contact information from PreK–8 schools in New York City.

The scraper starts from a list of school or official NYC education-directory URLs, discovers relevant internal pages, extracts structured school and contact information, cleans and deduplicates the results, and exports the data for downstream use.

Features

Seed-based crawling — Start from individual URLs or a seeds.txt file.

Automatic page discovery — Searches relevant internal pages such as:

Contact
Staff Directory
Administration
Faculty
Leadership
Parent Coordinator
Family Engagement
About

Playwright support — Handles dynamically rendered school websites.
Requests fallback — Can run without Playwright using --no-playwright.
Polite crawling — Supports rate limiting, concurrency limits, retries, and robots.txt.
Structured contact extraction — Extracts school information and publicly listed contacts.
Data cleaning — Normalizes names and emails and filters malformed records.
Contact deduplication — Combines duplicate contacts and merges multiple roles.
K–8 filtering — Generates a separate dataset containing schools serving K–8 grades.
Multiple export formats — Supports CSV, Excel, and JSON.
Fault tolerant — A failed school does not stop the entire crawling process.
Progress tracking — Uses tqdm to display crawling and parsing progress.

How It Works
Seed URLs
    │
    ▼
Web Crawler
    │
    ├── Discover relevant internal pages
    ├── Fetch webpages
    └── Collect crawl results
    │
    ▼
Parser
    │
    ├── Extract school information
    └── Extract publicly available contacts
    │
    ▼
Data Cleaning
    │
    ├── Clean names
    ├── Validate emails
    ├── Remove malformed contacts
    └── Deduplicate records
    │
    ▼
Export
    │
    ├── All cleaned records
    └── K–8 filtered records

The main pipeline is controlled through main.py, which provides the command-line interface and coordinates crawling, parsing, cleaning, and exporting. 

Project Structure
nyc_school_scraper/
│
├── scraper/
│   ├── __init__.py
│   ├── config.py
│   ├── utils.py
│   ├── crawler.py
│   ├── parser.py
│   ├── cleaner.py
│   └── exporter.py
│
├── data/
├── logs/
├── output/
│
├── main.py
├── generate_all_seeds.py
├── requirements.txt
├── seeds.txt
├── .gitignore
└── README.md

Main Components

File	Purpose

main.py	CLI entry point and main scraping pipeline
generate_all_seeds.py	Generates school-directory seed URLs
scraper/crawler.py	Crawls websites and discovers internal pages
scraper/parser.py	Extracts school/contact information
scraper/cleaner.py	Cleans and deduplicates school records
scraper/exporter.py	Exports records to CSV, Excel, and JSON
scraper/config.py	Central scraper configuration
scraper/utils.py	Logging and data-normalization utilities
seeds.txt	Input URLs for the scraper


Tech Stack
Python
Playwright
Requests
BeautifulSoup
lxml
Pandas
OpenPyXL
tqdm
asyncio
The required Python packages are defined in requirements.txt. requirements.txtTXT
Installation
1. Create a virtual environment
python -m venv .venv
2. Activate the environment
Windows PowerShell:
.venv\Scripts\Activate.ps1
macOS / Linux:
source .venv/bin/activate
3. Install dependencies
pip install -r requirements.txt
4. Install Playwright Chromium
playwright install chromium
Seed URLs
The scraper requires at least one seed URL.
You can provide URLs directly:
python main.py --seed-urls https://example-school.org
Or use a text file:
python main.py --seed-file seeds.txt
Each line in seeds.txt represents one starting URL. The current project uses NYC school-directory URLs such as:
https://www.schools.nyc.gov/schools/K200
https://www.schools.nyc.gov/schools/K201
https://www.schools.nyc.gov/schools/K202
https://www.schools.nyc.gov/schools/K203
https://www.schools.nyc.gov/schools/K204
seeds.txtTXTGenerating Seed URLs
generate_all_seeds.py can automatically generate school-directory URLs from DBN-style identifiers.
For example, the current script generates identifiers from K200 through K204 and writes the corresponding URLs into seeds.txt.  generate_all_seeds.pyPY
Run:
python generate_all_seeds.py
The generated URL format is:
https://www.schools.nyc.gov/schools/{DBN}
You can modify the range in generate_all_seeds.py to generate a different set of school URLs.
Usage
Basic Usage
python main.py --seed-file seeds.txt
Direct URLs
python main.py \
    --seed-urls \
    https://school-one.org \
    https://school-two.org
Custom Output Directory
python main.py \
    --seed-file seeds.txt \
    --output-dir ./output
Increase Crawl Coverage
python main.py \
    --seed-file seeds.txt \
    --max-pages 30 \
    --max-depth 3
Disable Playwright
python main.py \
    --seed-file seeds.txt \
    --no-playwright
Command-Line Options
The following options are supported by the current main.py:
Option	Default	Description
--seed-urls	—	One or more school homepage / directory URLs
--seed-file	—	File containing one seed URL per line
--output-dir	configured output directory	Directory for exported files
--output-basename	NYC_prek8_schools	Base name for the main export
--max-pages	1	Maximum pages crawled per school
--max-depth	0	Maximum link-following depth
--concurrency	5	Maximum concurrent requests per site
--max-sites	3	Maximum school sites processed in parallel
--rate-limit	1.0	Delay between requests to the same domain
--max-retries	3	Number of retries for failed requests
--no-playwright	Off	Disable Playwright
--ignore-robots	Off	Disable robots.txt checks
--log-level	INFO	Logging level


These arguments are defined directly in main.py. 
Data Processing
After crawling, the scraper processes each school record.
Name Cleaning
Names are:
Trimmed and normalized
Split into first, middle, and last names
Checked for malformed values
Filtered when the extracted value is actually a job title
The scraper specifically ignores title-only values such as:
Principal
Co-Principal
Assistant Principal
Parent Coordinator
Teacher
Director
Coordinator
Superintendent
Email Cleaning
Emails are:
Split when multiple addresses are found
Trimmed
Converted to lowercase
Validated using an @ check
Deduplicated
Contact Deduplication
If the same person appears under multiple roles, the scraper merges the records.
For example:
John Smith — Principal
John Smith — Parent Coordinator
becomes:
John Smith — Principal + Parent Coordinator
The scraper identifies contacts primarily by first and last name, with email used when a name is unavailable. 
K–8 Filtering
The project generates a separate dataset containing records whose grade information includes at least one K–8 grade.
Recognized grades include:
K
0K
01
02
03
04
05
06
07
08
main.pyPYThis allows the project to maintain:
A complete cleaned dataset
A K–8 filtered dataset
Output
The scraper exports cleaned school/contact records to the configured output directory.
The primary export uses the configured basename:
NYC_prek8_schools
The K–8 filtered export uses:
NYC_k8_filtered
The exporter supports:
CSV
Excel (.xlsx)
JSON
The .gitignore intentionally excludes generated CSV, Excel, and JSON files from Git, along with virtual environments and log files. .gitignore
Typical contact fields include:
School Name
District
Borough
County
State
Grades
Principal
Principal Email
Principal Phone Number
Assistant Principal
Assistant Principal Email
Assistant Principal Phone Number
Parent Coordinator
Parent Coordinator Email
Parent Coordinator Phone Number
Main Office Email
School Address
District Borough Number
Source URL
Last Crawled
Responsible Crawling
This project is intended for collecting publicly available information from official school or education-directory websites.
The scraper should be used responsibly:
Respect robots.txt.
Use reasonable request rates.
Avoid excessive concurrency.
Do not bypass authentication or access controls.
Do not collect private or non-public information.
Review website terms of use before large-scale crawling.
The --ignore-robots option is available, but disabling robots.txt compliance is not recommended.
Data Quality
Automated extraction cannot guarantee perfect results because school websites use different layouts and naming conventions.
In particular:
Some schools may not publish contact information.
Staff pages may use inconsistent HTML structures.
Role-to-person matching is heuristic.
Extracted contacts should be spot-checked before being used for important downstream tasks.
The project prioritizes structured and reusable data while recognizing that automated web extraction requires validation.
Extending the Project
Add New Page Keywords
Relevant page types can be expanded in:
scraper/config.py
Add New Fields
To extract another field:
Extend the SchoolRecord structure in scraper/parser.py.
Add the corresponding extraction logic.
Update the export mapping in scraper/exporter.py.
Crawl Another School Dataset
The scraper is seed-based, so a different set of official school URLs can be supplied through --seed-urls or a new seed file.
Example Workflow
# Create environment
python -m venv .venv

# Activate environment
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Install browser
playwright install chromium

# Generate seed URLs
python generate_all_seeds.py

# Run scraper
python main.py --seed-file seeds.txt
After completion, the generated datasets will be available in the configured output/ directory.
License
Provided as-is for working with information publicly published by schools and official education sources.
Always review the target website's terms of use and robots.txt before running the scraper at scale.