"""
IIU Data Engine — Flask Web Application
FYP: Natural Language for Business Intelligence

Run:
    pip install flask pdfplumber PyMuPDF
    python app.py

Then open:  http://localhost:5000
"""

import os
import re
import json
from pathlib import Path
from flask import Flask, render_template, request, jsonify, send_from_directory

# ─── Optional PDF libraries ───────────────────────────────────────
try:
    import pdfplumber
    PDF_PLUMBER_OK = True
except ImportError:
    PDF_PLUMBER_OK = False
    print("[WARNING] pdfplumber not installed. PDF extraction disabled.")

try:
    import fitz          # PyMuPDF
    FITZ_OK = True
except ImportError:
    FITZ_OK = False


# ══════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════

PDF_POLICY   = "Policy-Compendium-2020-2023-01012024.pdf"
PDF_STATUTES = "OCR-IIU-STATUTES-2.pdf"
OUTPUT_DIR   = "iiu_extracted_data"
DATA_FILE    = os.path.join(OUTPUT_DIR, "combined_iiu_data.json")

app = Flask(__name__)


# ══════════════════════════════════════════════════════════════════
#  SECTION 1 — PDF TEXT EXTRACTION
# ══════════════════════════════════════════════════════════════════

def extract_text_pdfplumber(pdf_path: str) -> dict:
    """Extract raw text from every page using pdfplumber."""
    pages = {}
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            pages[i] = text.strip() if text else ""
    return pages


def extract_text_fitz(pdf_path: str) -> dict:
    """Fallback extractor using PyMuPDF (better for scanned PDFs)."""
    if not FITZ_OK:
        return {}
    pages = {}
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        pages[i] = text.strip() if text else ""
    doc.close()
    return pages


def smart_extract(pdf_path: str) -> dict:
    """
    Use pdfplumber first.
    If >50% of pages are empty (scanned PDF), fall back to PyMuPDF.
    """
    if not PDF_PLUMBER_OK:
        return extract_text_fitz(pdf_path)

    pages = extract_text_pdfplumber(pdf_path)
    non_empty = sum(1 for t in pages.values() if len(t) > 50)

    if non_empty < len(pages) * 0.5 and FITZ_OK:
        pages = extract_text_fitz(pdf_path)

    return pages


# ══════════════════════════════════════════════════════════════════
#  SECTION 2 — POLICY COMPENDIUM PARSER
# ══════════════════════════════════════════════════════════════════

POLICY_HEADINGS = [
    "ADMISSION POLICY", "FEE POLICY", "EXAMINATION POLICY",
    "SCHOLARSHIP POLICY", "HOSTEL POLICY", "TRANSPORT POLICY",
    "ANTI-HARASSMENT POLICY", "RESULT POLICY", "DEGREE POLICY",
    "ACADEMIC INTEGRITY POLICY", "LIBRARY POLICY", "SPORT",
    "CODE OF CONDUCT", "RESEARCH POLICY", "PLAGIARISM POLICY",
    "ATTENDANCE POLICY", "LEAVE POLICY", "INTERNSHIP POLICY",
    "GRADING POLICY", "TRANSFER POLICY",
]

POLICY_SUB_PATTERNS = [
    r"^\d+\.\s+[A-Z]",
    r"^\d+\.\d+\s+[A-Z]",
    r"^[A-Z]\.\s+[A-Z]",
    r"^Article\s+\d+",
    r"^Section\s+\d+",
    r"^Clause\s+\d+",
]


def detect_policy_heading(line: str):
    clean = line.strip().upper()
    for h in POLICY_HEADINGS:
        if clean == h or clean.startswith(h + " ") or clean.startswith(h + ":"):
            return h
    return None


def is_sub_heading(line: str) -> bool:
    for pat in POLICY_SUB_PATTERNS:
        if re.match(pat, line.strip()):
            return True
    return False


def parse_policy_compendium(pages: dict) -> dict:
    """
    Parse Policy Compendium pages into a FLAT nested dict:
        { "ADMISSION POLICY": { "1. Eligibility": "text...", ... }, ... }

    FIX: No longer wraps content in {"full_text":..., "sections":{...}}.
    This prevents 'full_text' from appearing as a pseudo-section in search.
    """
    full_text = "\n".join(
        f"\n--- PAGE {n} ---\n{t}" for n, t in pages.items()
    )

    structured = {}
    current_heading = "GENERAL"
    current_section = "Overview"
    buffer = []

    def flush():
        content = " ".join(buffer).strip()
        if content:
            structured.setdefault(current_heading, {})
            existing = structured[current_heading].get(current_section, "")
            structured[current_heading][current_section] = (
                (existing + " " + content).strip()
            )

    for raw_line in full_text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("---"):
            continue

        heading = detect_policy_heading(line)
        if heading:
            flush()
            buffer = []
            current_heading = heading
            current_section = "Overview"
            structured[current_heading] = {}
            continue

        if is_sub_heading(line):
            flush()
            buffer = []
            current_section = line
            continue

        buffer.append(line)

    flush()
    return structured


# ══════════════════════════════════════════════════════════════════
#  SECTION 3 — IIU STATUTES PARSER
# ══════════════════════════════════════════════════════════════════

STATUTE_HEADINGS = {
    "IIU STATUTES 2006": [
        "FACULTIES", "BOARDS OF FACULTIES", "DEAN", "TEACHING DEPARTMENTS",
        "BOARD OF STUDIES", "INSTITUTES/ACADEMIES/SCHOOLS/CENTRES",
        "BOARD OF ADVANCED STUDIES AND RESEARCH", "THE SELECTION BOARD",
        "FUNCTIONS OF SELECTION BOARD", "APPOINTMENT OF PROFESSOR EMERITUS",
        "FINANCE AND PLANNING COMMITTEE", "STUDENTS DISCIPLINE COMMITTEE",
        "THE PROVOST", "BUDGET AND ACCOUNTS", "AUDIT", "SPECIAL RESERVE FUND",
    ],
    "IIU TENURE TRACK SYSTEM STATUTES 2005": [
        "SHORT TITLE", "TENURE TRACK SYSTEM",
    ],
    "IIU PENSION STATUTES 2004": [
        "SHORT TITLE & COMMENCEMENT", "DEFINITIONS", "EXTENT OF APPLICATION",
        "QUALIFYING SERVICE FOR PENSION", "AUTHORITY COMPETENT TO GRANT PENSION",
        "ANTICIPATORY PENSION", "APPLICATION OF GOVERNMENT PENSION RULES",
        "PENSION FUND", "REPEAL & SAVINGS",
    ],
    "IIU STATUTES 2000 - AFFILIATION": [
        "TITLE", "DEFINITIONS", "APPLICATION FOR AFFILIATION",
        "CRITERIA FOR ELIGIBILITY", "UNDERTAKINGS REQUIRED",
        "PROCEDURE FOR AFFILIATION", "CONDITIONS AND PROCEDURE FOR DE-AFFILIATION",
        "FEES FOR AFFILIATION AND SHARING IN INCOME",
    ],
    "IIU STATUTES 1992": [
        "FOR GRANT OF BPS-21 AND BPS-22", "ELIGIBILITY", "PROCEDURE OF PROMOTION",
        "FOR CONFERMENT OF AN HONORARY DEGREE",
    ],
    "IIU STATUTES 1987 - SERVICE": [
        "DEFINITIONS", "CLASSIFICATION OF UNIVERSITY EMPLOYEES", "SENIORITY",
        "APPOINTMENTS", "PROBATION", "CONFIRMATION", "TERMINATION OF SERVICE",
        "RESIGNATION", "RETIREMENT", "PAY & OTHER EMOLUMENTS",
        "ANNUAL INCREMENTS", "TRAINING ABROAD",
    ],
    "IIU STATUTES 1987 - LEAVE": [
        "CASUAL LEAVE", "EARNING & ACCUMULATION OF LEAVE", "LEAVE ON FULL PAY",
        "STUDY LEAVE", "EXTRAORDINARY LEAVE", "MATERNITY LEAVE", "SPECIAL LEAVE",
        "SABBATICAL LEAVE", "DISABILITY LEAVE",
    ],
    "IIU STATUTES 1987 - EFFICIENCY & DISCIPLINE": [
        "GROUNDS FOR PENALTY", "PENALTIES", "INQUIRY PROCEDURE",
        "POWERS OF INQUIRY OFFICER", "APPEAL", "APPEARANCE OF COUNSEL",
    ],
}

ALL_STATUTE_SECTIONS = [
    (group, section)
    for group, sections in STATUTE_HEADINGS.items()
    for section in sections
]

STATUTE_VERSION_MARKERS = {
    "THE IIU STATUTES-2006":        "IIU STATUTES 2006",
    "THE IIU STATUTES-2005":        "IIU TENURE TRACK SYSTEM STATUTES 2005",
    "IIU PENSION STATUTES 2004":    "IIU PENSION STATUTES 2004",
    "THE IIU STATUTES-2000":        "IIU STATUTES 2000 - AFFILIATION",
    "THE IIU STATUTES-1992":        "IIU STATUTES 1992",
    "THE IIU STATUTES-1987":        "IIU STATUTES 1987 - SERVICE",
    "PART II":                       "IIU STATUTES 1987 - LEAVE",
    "PART III":                      "IIU STATUTES 1987 - EFFICIENCY & DISCIPLINE",
    "PART I":                        "IIU STATUTES 1987 - SERVICE",
}


def detect_statute_version(line: str):
    clean = line.strip().upper()
    for marker, version in STATUTE_VERSION_MARKERS.items():
        if marker.upper() in clean:
            return version
    return None


def detect_statute_section(line: str):
    clean = line.strip().upper()
    clean_no_num = re.sub(r"^\d+[\.\d]*\s*", "", clean).strip()
    for group, section in ALL_STATUTE_SECTIONS:
        if clean_no_num == section or clean == section:
            return group, section
        if len(section) > 10 and section in clean:
            return group, section
    return None


def parse_statutes(pages: dict) -> dict:
    """Parse IIU Statutes pages into a nested dict."""
    full_text = "\n".join(
        f"\n--- PAGE {n} ---\n{t}" for n, t in pages.items()
    )

    structured = {}
    current_group   = "IIU STATUTES 2006"
    current_section = "Introduction"
    buffer = []

    def flush():
        content = " ".join(buffer).strip()
        if content:
            structured.setdefault(current_group, {})
            existing = structured[current_group].get(current_section, "")
            structured[current_group][current_section] = (existing + " " + content).strip()

    for raw_line in full_text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("---"):
            continue

        version = detect_statute_version(line)
        if version:
            flush()
            buffer = []
            current_group   = version
            current_section = "Overview"
            continue

        sec = detect_statute_section(line)
        if sec:
            flush()
            buffer = []
            current_group, current_section = sec
            continue

        buffer.append(line)

    flush()
    return structured


# ══════════════════════════════════════════════════════════════════
#  SECTION 4 — TEXT CLEANER
# ══════════════════════════════════════════════════════════════════

def clean_text(text: str):

    # Remove page markers
    text = re.sub(r"---\s*PAGE\s*\d+\s*---", "", text)

    # Remove standalone page numbers
    text = re.sub(r"^\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)

    # Remove PDF escape artifacts
    text = re.sub(r"\\{1,3}'s", "'s", text)
    text = re.sub(r"\\{1,3}':", ":", text)
    text = re.sub(r"\\{1,3}',", ",", text)
    text = re.sub(r"\\{1,3}'", "'", text)
    text = re.sub(r'\\{1,3}"', '"', text)

    # Remove duplicate OCR letters
    text = re.sub(r'([A-Za-z])\1+', r'\1', text)

    # Fix OCR overlapping text
    text = re.sub(r'([A-Za-z])([A-Za-z])\1\2+', r'\1\2', text)

    # Remove extra spaces/newlines
    text = re.sub(r"\s+", " ", text)

    return text.strip()

def clean_structured(data):
    if isinstance(data, dict):
        return {k: clean_structured(v) for k, v in data.items()}
    if isinstance(data, str):
        return clean_text(data)
    return data


# ══════════════════════════════════════════════════════════════════
#  SECTION 5 — NLP / SEARCH HELPERS
# ══════════════════════════════════════════════════════════════════

def _iter_sections(doc_data: dict):
    """
    Yield (heading, section_name, text) tuples from a document dict.

    FIX: Handles BOTH data shapes:
      Shape A (flat — new parser output):
          { "ADMISSION POLICY": { "1. Eligibility": "text..." } }

      Shape B (legacy nested — old parser / loaded JSON):
          { "ADMISSION POLICY": { "full_text": "...", "sections": { "1.": "text..." } } }

    Skips 'full_text' keys so they never surface as fake section names.
    """
    for heading, heading_data in doc_data.items():
        if not isinstance(heading_data, dict):
            # Plain string value at heading level
            if isinstance(heading_data, str) and heading_data.strip():
                yield heading, heading, heading_data
            continue

        # Detect Shape B
        if "sections" in heading_data and isinstance(heading_data["sections"], dict):
            sections_dict = heading_data["sections"]
        else:
            # Shape A — skip the 'full_text' sentinel key
            sections_dict = {
                k: v for k, v in heading_data.items()
                if k != "full_text"
            }

        for section, text in sections_dict.items():
            if isinstance(text, dict):
                # Deeper nesting — flatten one more level
                for sub_sec, sub_text in text.items():
                    if isinstance(sub_text, str) and sub_text.strip():
                        yield heading, f"{section} › {sub_sec}", sub_text
            elif isinstance(text, str) and text.strip():
                yield heading, section, text


def search_documents(all_data: dict, keyword: str) -> list:
    """
    Keyword search across all parsed documents.

    FIX:
    - Uses _iter_sections() so 'full_text' never appears as a result heading.
    - Applies clean_text() to each snippet before display.
    - Returns richer context (heading + section properly labelled).
    """
    results = []
    kw = keyword.lower()

    for doc_name, doc_data in all_data.items():
        if not isinstance(doc_data, dict):
            continue

        for heading, section, raw_text in _iter_sections(doc_data):
            t = clean_text(raw_text)
            if not t:
                continue

            match_in_text    = kw in t.lower()
            match_in_heading = kw in heading.lower()
            match_in_section = kw in section.lower()

            if not (match_in_text or match_in_heading or match_in_section):
                continue

            # Build a clean, readable snippet around the keyword
            lower_t = t.lower()
            if match_in_text:
                idx   = lower_t.find(kw)
                start = max(0, idx - 100)
                end   = min(len(t), idx + 250)
                prefix  = "…" if start > 0 else ""
                suffix  = "…" if end < len(t) else ""
                snippet = prefix + t[start:end].strip() + suffix
            else:
                # Keyword only in heading/section name — show first 300 chars of text
                snippet = t[:300].strip() + ("…" if len(t) > 300 else "")

            results.append({
                "document": doc_name,
                "heading":  heading,
                "section":  section,
                "snippet":  snippet,
                "text":     t,
            })

    return results[:30]


def build_qa_dataset(all_data: dict) -> list:
    """Build Q&A pairs from structured data for NLP training."""
    qa = []
    for doc_name, doc_data in all_data.items():
        if not isinstance(doc_data, dict):
            continue
        for heading, section, text in _iter_sections(doc_data):
            t = clean_text(text)
            if len(t) > 50:
                qa.append({
                    "question": f"What does \"{section}\" say under {heading}?",
                    "answer":   t[:500],
                    "source":   f"{doc_name} > {heading} > {section}",
                })
    return qa


def corpus_stats(all_data: dict) -> dict:
    """Return summary statistics for the loaded corpus."""
    total_sections = 0
    total_words    = 0
    total_docs     = len(all_data)

    for doc_data in all_data.values():
        if not isinstance(doc_data, dict):
            continue
        for _, _, text in _iter_sections(doc_data):
            total_sections += 1
            total_words    += len(clean_text(text).split())

    qa_count = len(build_qa_dataset(all_data))

    return {
        "documents": total_docs,
        "sections":  total_sections,
        "words":     total_words,
        "qa_pairs":  qa_count,
    }


# ══════════════════════════════════════════════════════════════════
#  SECTION 6 — DATA LOADER
# ══════════════════════════════════════════════════════════════════

# Built-in demo data (used when no PDFs or JSON are found)
# NOTE: This now uses the FLAT structure: {heading: {section: text}}
DEMO_DATA = {
    "POLICY_COMPENDIUM": {
        "ADMISSION POLICY": {
            "Eligibility": "Students must have at least 60% marks in intermediate or equivalent. International students must submit an equivalence certificate from IBCC.",
            "Documents Required": "CNIC, Matric certificate, Intermediate certificate, Character certificate, and two passport-size photographs.",
            "Admission Process": "Applications are submitted via the IIU admissions portal. Shortlisted candidates are called for an entry test and interview.",
            "Quota Policy": "Seats reserved: Merit 50%, Provincial 20%, Foreign 10%, Special persons 2%, Sports 3%, Hafiz-e-Quran 5%.",
        },
        "FEE POLICY": {
            "General": "Fee is payable before semester commencement. Fee once deposited is non-refundable except in special circumstances.",
            "Late Fee": "A surcharge of Rs. 500 per day applies after the due date. Students failing to pay within 7 days grace period are de-registered.",
            "Refund Policy": "100% refund before class commencement. Reduces by 25% per week for 4 weeks, then no refund.",
        },
        "EXAMINATION POLICY": {
            "Attendance Requirement": "A minimum of 75% attendance per course is mandatory. Students below 75% are barred from finals and awarded an F grade.",
            "Grading System": "Relative grading: A+ (4.0), A (4.0), A- (3.7), B+ (3.3), B (3.0), B- (2.7), C+ (2.3), C (2.0), D (1.0), F (0.0).",
            "Cheating and Misconduct": "Use of unfair means results in cancellation of the paper to expulsion depending on severity.",
        },
        "SCHOLARSHIP POLICY": {
            "Merit Scholarship": "Students in the top 10% of their batch are eligible for 50% to 100% tuition fee scholarships.",
            "Need-Based Scholarship": "Students from families with monthly income below Rs. 30,000 may apply with supporting government documents.",
            "Hafiz-e-Quran Scholarship": "Full tuition fee waiver upon verification by the Faculty of Islamic Studies.",
        },
        "ATTENDANCE POLICY": {
            "Minimum Attendance": "75% attendance is the minimum requirement. Short attendance results in being barred from finals.",
            "Leave of Absence": "Medical leave requires a certificate from a registered MBBS doctor submitted within 7 days.",
        },
    },
    "IIU_STATUTES": {
        "IIU STATUTES 2006": {
            "Overview": "Govern the academic and administrative structure of IIU, defining Faculties, Boards, Dean's Office, Teaching Departments, and related bodies.",
            "FACULTIES": "The University shall have: (i) Faculty of Islamic Studies; (ii) Faculty of Shariah and Law; (iii) Faculty of Management Sciences; (iv) Faculty of Education; (v) Faculty of Social Sciences; (vi) Faculty of Engineering and Technology.",
            "DEAN": "There shall be a Dean of each Faculty, appointed by the Rector for three years, eligible for reappointment. The Dean is the academic and administrative head.",
            "TEACHING DEPARTMENTS": "There shall be a Teaching Department for each major subject. Each Department shall have a Head appointed by the Rector on the Dean's recommendation.",
            "STUDENTS DISCIPLINE COMMITTEE": "Consists of the Rector (Chairperson), relevant Dean, Registrar, and two senior faculty members. Handles all student misconduct cases.",
            "BUDGET AND ACCOUNTS": "A common University Fund shall be maintained. All income and expenditure shall be entered in books of accounts under the Finance Director.",
        },
        "IIU PENSION STATUTES 2004": {
            "Overview": "Govern pension entitlements and procedures for all regular IIU employees.",
            "DEFINITIONS": "Pension means monthly payment to a retired employee. Qualifying Service means service period counting towards pension. Competent Authority means the Rector.",
            "QUALIFYING SERVICE FOR PENSION": "Minimum 25 years of qualifying service for a full pension. 10 to 25 years entitles an employee to a proportionate pension.",
            "PENSION FUND": "Employee contributes 10% of basic pay; University contributes 15% monthly to the Pension Fund.",
        },
        "IIU STATUTES 1987 - SERVICE": {
            "Overview": "Regulate terms and conditions of service for all categories of University employees.",
            "DEFINITIONS": "Ad-hoc Appointment means temporary appointment not exceeding 6 months. Competent Authority means the appointing authority for each grade.",
            "PROBATION": "All appointments are on probation for two years, extendable by one year. Confirmation is issued only upon satisfactory completion.",
            "RETIREMENT": "Superannuation age is 60 years. Service may be extended year-by-year up to 65 with Rector's approval.",
        },
        "IIU STATUTES 1987 - LEAVE": {
            "Overview": "Regulate all categories of leave admissible to University employees.",
            "CASUAL LEAVE": "BPS 1-15: 10 days per year. BPS 16 and above: 20 days per year. Non-accumulative and non-encashable.",
            "MATERNITY LEAVE": "90 days on full pay. Granted not more than three times in the entire service career.",
            "SABBATICAL LEAVE": "Granted to senior academic staff for research or study after 7 continuous years of service. Up to one year on full pay.",
        },
        "IIU STATUTES 1987 - EFFICIENCY & DISCIPLINE": {
            "Overview": "Prescribe grounds for disciplinary action, applicable penalties, and inquiry procedures.",
            "GROUNDS FOR PENALTY": "(a) Inefficiency or incompetence; (b) Misconduct; (c) Corruption or moral turpitude; (d) Subversive activities; (e) Absence without leave.",
            "PENALTIES": "Minor: Censure, Withholding increment, Recovery of loss. Major: Reduction in rank, Compulsory retirement, Removal, Dismissal.",
            "APPEAL": "An aggrieved employee may appeal to the next higher authority within 30 days. The appellate authority shall decide within 60 days.",
        },
    },
}


def load_data() -> dict:
    """Load data: JSON file first, then fall back to built-in demo data."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEMO_DATA


# Load once at startup
CORPUS = load_data()


# ══════════════════════════════════════════════════════════════════
#  SECTION 7 — FLASK ROUTES
# ══════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    """Serve the main HTML page."""
    return render_template("index.html")


# ── REST API ─────────────────────────────────────────────────────

@app.route("/api/stats")
def api_stats():
    """GET /api/stats — corpus statistics."""
    return jsonify(corpus_stats(CORPUS))


@app.route("/api/search", methods=["POST"])
def api_search():
    """POST /api/search — keyword search across all documents.
    Body: {"query": "admission"}
    """
    data  = request.get_json(force=True)
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    results = search_documents(CORPUS, query)
    return jsonify({"query": query, "count": len(results), "results": results})


@app.route("/api/documents")
def api_documents():
    """GET /api/documents — list all documents and their headings."""
    docs = {}
    for doc_key, doc_data in CORPUS.items():
        if isinstance(doc_data, dict):
            headings = {}
            for heading, _, _ in _iter_sections(doc_data):
                headings.setdefault(heading, [])
            # Collect sections per heading
            for heading, section, _ in _iter_sections(doc_data):
                if section not in headings[heading]:
                    headings[heading].append(section)
            docs[doc_key] = headings
    return jsonify(docs)


@app.route("/api/section")
def api_section():
    """GET /api/section?doc=POLICY_COMPENDIUM&heading=ADMISSION+POLICY&section=Eligibility"""
    doc_key = request.args.get("doc", "")
    heading = request.args.get("heading", "")
    section = request.args.get("section", "")

    doc_data = CORPUS.get(doc_key)
    if not doc_data:
        return jsonify({"error": f"Document '{doc_key}' not found"}), 404

    heading_data = doc_data.get(heading)
    if heading_data is None:
        return jsonify({"error": f"Heading '{heading}' not found"}), 404

    if section:
        # Navigate both flat and legacy-nested shapes
        if isinstance(heading_data, dict):
            sections_dict = (
                heading_data.get("sections", {})
                if "sections" in heading_data
                else {k: v for k, v in heading_data.items() if k != "full_text"}
            )
            text = sections_dict.get(section)
            if text is None:
                return jsonify({"error": f"Section '{section}' not found"}), 404
            return jsonify({
                "doc": doc_key,
                "heading": heading,
                "section": section,
                "text": clean_text(str(text)),
            })

    return jsonify({"doc": doc_key, "heading": heading, "data": heading_data})


@app.route("/api/qa")
def api_qa():
    """GET /api/qa — return generated Q&A dataset."""
    qa = build_qa_dataset(CORPUS)
    return jsonify({"count": len(qa), "qa": qa})


@app.route("/api/extract", methods=["POST"])
def api_extract():
    """POST /api/extract — run PDF extraction pipeline."""
    global CORPUS

    if not PDF_PLUMBER_OK:
        return jsonify({"error": "pdfplumber not installed. Run: pip install pdfplumber"}), 500

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    extracted = {}
    log = []

    # Policy Compendium
    if os.path.exists(PDF_POLICY):
        log.append(f"Extracting {PDF_POLICY}…")
        pages  = smart_extract(PDF_POLICY)
        parsed = parse_policy_compendium(pages)
        parsed = clean_structured(parsed)
        extracted["POLICY_COMPENDIUM"] = parsed
        log.append(f"  → {len(parsed)} policy headings extracted.")
    else:
        log.append(f"[SKIP] {PDF_POLICY} not found.")

    # IIU Statutes
    if os.path.exists(PDF_STATUTES):
        log.append(f"Extracting {PDF_STATUTES}…")
        pages  = smart_extract(PDF_STATUTES)
        parsed = parse_statutes(pages)
        parsed = clean_structured(parsed)
        extracted["IIU_STATUTES"] = parsed
        log.append(f"  → {len(parsed)} statute groups extracted.")
    else:
        log.append(f"[SKIP] {PDF_STATUTES} not found.")

    if not extracted:
        return jsonify({"error": "No PDFs found.", "log": log}), 404

    # Save combined JSON
    combined_path = os.path.join(OUTPUT_DIR, "combined_iiu_data.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(extracted, f, indent=2, ensure_ascii=False)

    # Save Q&A dataset
    qa = build_qa_dataset(extracted)
    with open(os.path.join(OUTPUT_DIR, "qa_dataset.json"), "w", encoding="utf-8") as f:
        json.dump(qa, f, indent=2, ensure_ascii=False)

    log.append(f"Saved: {combined_path}")
    log.append(f"Q&A pairs generated: {len(qa)}")

    # Reload corpus
    CORPUS = load_data()
    log.append("Corpus reloaded in memory.")

    return jsonify({"success": True, "log": log, "stats": corpus_stats(CORPUS)})


@app.route("/api/download/json")
def download_json():
    """GET /api/download/json — download combined JSON data file."""
    if not os.path.exists(DATA_FILE):
        response = app.response_class(
            response=json.dumps(CORPUS, indent=2, ensure_ascii=False),
            status=200,
            mimetype="application/json",
        )
        response.headers["Content-Disposition"] = "attachment; filename=iiu_data.json"
        return response
    return send_from_directory(OUTPUT_DIR, "combined_iiu_data.json", as_attachment=True)


@app.route("/api/download/qa")
def download_qa():
    """GET /api/download/qa — download Q&A dataset."""
    qa = build_qa_dataset(CORPUS)
    response = app.response_class(
        response=json.dumps(qa, indent=2, ensure_ascii=False),
        status=200,
        mimetype="application/json",
    )
    response.headers["Content-Disposition"] = "attachment; filename=qa_dataset.json"
    return response


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "═" * 55)
    print("  IIU Data Engine — Flask Web Application")
    print("  FYP: Natural Language for Business Intelligence")
    print("═" * 55)
    print(f"  Policy PDF   : {PDF_POLICY}")
    print(f"  Statutes PDF : {PDF_STATUTES}")
    print(f"  Data file    : {DATA_FILE}")
    print(f"  pdfplumber   : {'✓' if PDF_PLUMBER_OK else '✗ (install: pip install pdfplumber)'}")
    print(f"  PyMuPDF      : {'✓' if FITZ_OK else '✗ (install: pip install PyMuPDF)'}")

    using_demo = not os.path.exists(DATA_FILE)
    print(f"\n  Data source  : {'⚠ Demo data (no JSON found)' if using_demo else '✓ ' + DATA_FILE}")
    print(f"\n  Open browser : http://localhost:5000")
    print("═" * 55 + "\n")

    app.run(debug=True, host="0.0.0.0", port=5000)