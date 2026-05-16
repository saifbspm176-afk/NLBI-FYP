"""
IIU PDF Data Extractor for FYP - Natural Language for Business Intelligence
Extracts structured data from:
1. Policy-Compendium-2020-2023 (Admission Policy etc.)
2. OCR-IIU-STATUTES-2 (IIU Statutes)

Author: FYP Project
"""

import re
import json
import os
from pathlib import Path

# ─────────────────────────────────────────────
# Install required libraries (run once)
# pip install pdfplumber PyMuPDF
# ─────────────────────────────────────────────

try:
    import pdfplumber
    print("[OK] pdfplumber loaded")
except ImportError:
    print("[ERROR] Install pdfplumber: pip install pdfplumber")
    exit(1)

try:
    import fitz  # PyMuPDF
    print("[OK] PyMuPDF loaded")
except ImportError:
    print("[WARNING] PyMuPDF not found. Install: pip install PyMuPDF")
    fitz = None


# ══════════════════════════════════════════════════════════════════
#  SECTION 1: RAW TEXT EXTRACTION
# ══════════════════════════════════════════════════════════════════

def extract_text_pdfplumber(pdf_path: str) -> dict:
    """
    Extracts raw text from every page of a PDF using pdfplumber.
    Returns: {page_number: page_text}
    """
    pages = {}
    print(f"\n[INFO] Extracting text from: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if text:
                pages[i] = text.strip()
            else:
                pages[i] = ""
    print(f"[INFO] Total pages extracted: {len(pages)}")
    return pages


def extract_text_fitz(pdf_path: str) -> dict:
    """
    Fallback extractor using PyMuPDF (better for OCR-scanned PDFs).
    Returns: {page_number: page_text}
    """
    if fitz is None:
        return {}
    pages = {}
    doc = fitz.open(pdf_path)
    for i, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages[i] = text.strip() if text else ""
    doc.close()
    return pages


def smart_extract(pdf_path: str) -> dict:
    """
    Uses pdfplumber first; if pages are mostly empty (scanned PDF), 
    falls back to PyMuPDF.
    """
    pages = extract_text_pdfplumber(pdf_path)
    non_empty = sum(1 for t in pages.values() if len(t) > 50)
    if non_empty < len(pages) * 0.5 and fitz:
        print("[INFO] Switching to PyMuPDF for better OCR extraction...")
        pages = extract_text_fitz(pdf_path)
    return pages


# ══════════════════════════════════════════════════════════════════
#  SECTION 2: POLICY COMPENDIUM PARSER
#  (Admission Policy, Fee Policy, Examination Policy, etc.)
# ══════════════════════════════════════════════════════════════════

# Known major headings in the Policy Compendium
POLICY_HEADINGS = [
    "ADMISSION POLICY",
    "FEE POLICY",
    "EXAMINATION POLICY",
    "SCHOLARSHIP POLICY",
    "HOSTEL POLICY",
    "TRANSPORT POLICY",
    "ANTI-HARASSMENT POLICY",
    "RESULT POLICY",
    "DEGREE POLICY",
    "ACADEMIC INTEGRITY POLICY",
    "LIBRARY POLICY",
    "SPORT",
    "CODE OF CONDUCT",
    "RESEARCH POLICY",
    "PLAGIARISM POLICY",
    "ATTENDANCE POLICY",
    "LEAVE POLICY",
    "INTERNSHIP POLICY",
    "GRADING POLICY",
    "TRANSFER POLICY",
]

# Sub-section patterns
POLICY_SUB_PATTERNS = [
    r"^\d+\.\s+[A-Z]",           # "1. ELIGIBILITY"
    r"^\d+\.\d+\s+[A-Z]",        # "1.1 Requirements"
    r"^[A-Z]\.\s+[A-Z]",         # "A. General Rules"
    r"^Article\s+\d+",            # "Article 1"
    r"^Section\s+\d+",            # "Section 1"
    r"^Clause\s+\d+",             # "Clause 1"
]


def detect_policy_heading(line: str) -> str | None:
    """Returns the heading name if line matches a known policy heading."""
    clean = line.strip().upper()
    for h in POLICY_HEADINGS:
        if clean == h or clean.startswith(h + " ") or clean.startswith(h + ":"):
            return h
    return None


def is_sub_heading(line: str) -> bool:
    """Returns True if line looks like a sub-section heading."""
    for pat in POLICY_SUB_PATTERNS:
        if re.match(pat, line.strip()):
            return True
    return False


def parse_policy_compendium(pages: dict) -> dict:
    """
    Parses the Policy Compendium PDF into a structured dict:
    {
        "ADMISSION POLICY": {
            "full_text": "...",
            "sections": {
                "1. Eligibility": "text...",
                ...
            }
        },
        ...
    }
    """
    print("\n[INFO] Parsing Policy Compendium...")

    # Merge all pages into one text block (with page markers)
    full_text = ""
    for pnum, text in pages.items():
        full_text += f"\n\n--- PAGE {pnum} ---\n\n{text}"

    structured = {}
    current_heading = "GENERAL"
    current_section = "Introduction"
    buffer = []

    def flush():
        content = " ".join(buffer).strip()
        if content:
            if current_heading not in structured:
                structured[current_heading] = {"full_text": "", "sections": {}}
            structured[current_heading]["sections"][current_section] = content
            structured[current_heading]["full_text"] += f"\n{content}"

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
            structured[current_heading] = {"full_text": "", "sections": {}}
            continue

        if is_sub_heading(line):
            flush()
            buffer = []
            current_section = line
            continue

        buffer.append(line)

    flush()  # flush last buffer
    print(f"[INFO] Policies found: {list(structured.keys())}")
    return structured


# ══════════════════════════════════════════════════════════════════
#  SECTION 3: IIU STATUTES PARSER
# ══════════════════════════════════════════════════════════════════

STATUTE_HEADINGS = {
    "IIU STATUTES 2006": [
        "FACULTIES",
        "BOARDS OF FACULTIES",
        "DEAN",
        "TEACHING DEPARTMENTS",
        "BOARD OF STUDIES",
        "INSTITUTES/ACADEMIES/SCHOOLS/CENTRES",
        "BOARD OF ADVANCED STUDIES AND RESEARCH",
        "THE SELECTION BOARD",
        "FUNCTIONS OF SELECTION BOARD",
        "APPOINTMENT OF PROFESSOR EMERITUS",
        "FINANCE AND PLANNING COMMITTEE",
        "FUNCTIONS OF FINANCE & PLANNING COMMITTEE",
        "STUDENTS DISCIPLINE COMMITTEE",
        "THE PROVOST",
        "BUDGET AND ACCOUNTS",
        "AUDIT",
        "SPECIAL RESERVE FUND",
        "SPECIAL GRANTS, DONATIONS, ENDOWMENTS",
        "REPEAL AND SAVINGS",
    ],
    "IIU TENURE TRACK SYSTEM STATUTES 2005": [
        "SHORT TITLE",
        "TENURE TRACK SYSTEM",
    ],
    "IIU PENSION STATUTES 2004": [
        "SHORT TITLE & COMMENCEMENT",
        "DEFINITIONS",
        "EXTENT OF APPLICATION",
        "EXCEPTIONS",
        "QUALIFYING SERVICE FOR PENSION",
        "ACCEPTANCE OF PENSION LIABILITY",
        "PAYMENT OF PENSION LIABILITY",
        "AUTHORITY COMPETENT TO GRANT PENSION",
        "ANTICIPATORY PENSION",
        "APPLICATION OF GOVERNMENT PENSION RULES",
        "AMENDMENTS",
        "PENSION FUND",
        "REPEAL & SAVINGS",
        "REMOVAL OF DIFFICULTIES",
        "RELAXATION",
        "PROTECTION OF EMPLOYEES",
    ],
    "IIU STATUTES 2000 - AFFILIATION": [
        "TITLE",
        "DEFINITIONS",
        "APPLICATION FOR AFFILIATION",
        "CRITERIA FOR ELIGIBILITY",
        "UNDERTAKINGS REQUIRED",
        "PROCEDURE FOR AFFILIATION",
        "REPORTING REQUIREMENTS",
        "CONDITIONS AND PROCEDURE FOR DE-AFFILIATION",
        "FEES FOR AFFILIATION AND SHARING IN INCOME",
    ],
    "IIU STATUTES 1992": [
        "FOR GRANT OF BPS-21 AND BPS-22",
        "EXTENT OF APPLICATION",
        "PROVISION OF POSTS",
        "ELIGIBILITY",
        "PROCEDURE OF PROMOTION",
        "FOR CONFERMENT OF AN HONORARY DEGREE",
    ],
    "IIU STATUTES 1987 - SERVICE": [
        "DEFINITIONS",
        "EXTENT OF APPLICATION",
        "CLASSIFICATION OF UNIVERSITY EMPLOYEES",
        "SENIORITY",
        "TERMS AND CONDITIONS OF SERVICE",
        "APPOINTMENTS",
        "SELECTION OF EMPLOYEES",
        "REVERSION",
        "PROBATION",
        "CONFIRMATION",
        "LIEN",
        "ADDITIONAL CHARGE",
        "TERMINATION OF SERVICE",
        "RESIGNATION",
        "PHYSICAL FITNESS",
        "RE-EMPLOYMENT",
        "PAY & OTHER EMOLUMENTS",
        "HIGHER STARTING PAY",
        "ANNUAL INCREMENTS",
        "ACCELERATED INCREMENTS",
        "HONORARIA",
        "SERVICE ON DEPUTATION",
        "RECORD OF SERVICE",
        "TRANSFER",
        "RETIREMENT",
        "PENSION FUNDS",
        "GENERAL/CONTRIBUTORY PROVIDENT FUND",
        "GRATUITY",
        "WELFARE BENEFITS",
        "TRAINING ABROAD",
        "REPEAL & SAVINGS",
        "REMOVAL OF DIFFICULTIES",
        "RELAXATION IN CASE OF UNDUE HARDSHIP",
        "PROTECTION TO EMPLOYEES",
    ],
    "IIU STATUTES 1987 - LEAVE": [
        "GENERAL",
        "COMPETENT AUTHORITY",
        "CASUAL LEAVE",
        "EARNING & ACCUMULATION OF LEAVE",
        "LEAVE ON FULL PAY",
        "LEAVE ON HALF PAY",
        "STUDY LEAVE",
        "EXTRAORDINARY LEAVE",
        "RECREATION LEAVE",
        "MATERNITY LEAVE",
        "SPECIAL LEAVE",
        "LEAVE NOT DUE",
        "DISABILITY LEAVE",
        "LEAVE EX-PAKISTAN",
        "QUARANTINE LEAVE",
        "SABBATICAL LEAVE",
        "ENCASHMENT OF LEAVE PREPARATORY TO RETIREMENT",
        "DEATH DURING SERVICE",
    ],
    "IIU STATUTES 1987 - EFFICIENCY & DISCIPLINE": [
        "SHORT TITLE, COMMENCEMENT & APPLICATION",
        "DEFINITIONS",
        "GROUNDS FOR PENALTY",
        "PENALTIES",
        "INQUIRY PROCEDURE",
        "PROCEDURE TO BE OBSERVED BY THE INQUIRY OFFICER",
        "REVISION",
        "POWERS OF INQUIRY OFFICER & INQUIRY COMMITTEE",
        "STATUTE 5 NOT TO APPLY IN CERTAIN CASES",
        "ACTION IN RESPECT OF AN EMPLOYEE",
        "PROCEDURE OF INQUIRY AGAINST OFFICERS LENT",
        "APPEAL",
        "APPEARANCE OF COUNSEL",
    ],
}

# Flat list for quick matching
ALL_STATUTE_SECTIONS = []
for group, sections in STATUTE_HEADINGS.items():
    for s in sections:
        ALL_STATUTE_SECTIONS.append((group, s))

# Statute version markers
STATUTE_VERSION_MARKERS = {
    "THE IIU STATUTES-2006": "IIU STATUTES 2006",
    "THE IIU STATUTES-2005": "IIU TENURE TRACK SYSTEM STATUTES 2005",
    "IIU PENSION STATUTES 2004": "IIU PENSION STATUTES 2004",
    "THE IIU STATUTES-2000": "IIU STATUTES 2000 - AFFILIATION",
    "THE IIU STATUTES-1992": "IIU STATUTES 1992",
    "THE IIU STATUTES-1987": "IIU STATUTES 1987 - SERVICE",
    "PART II": "IIU STATUTES 1987 - LEAVE",
    "PART III": "IIU STATUTES 1987 - EFFICIENCY & DISCIPLINE",
    "PART I": "IIU STATUTES 1987 - SERVICE",
}


def detect_statute_version(line: str) -> str | None:
    clean = line.strip().upper()
    for marker, version in STATUTE_VERSION_MARKERS.items():
        if marker.upper() in clean:
            return version
    return None


def detect_statute_section(line: str) -> tuple | None:
    """Returns (group, section_name) if the line matches a known statute section."""
    clean = line.strip().upper()
    # Remove numbering like "1.", "10.", "1.1", etc.
    clean_no_num = re.sub(r"^\d+[\.\d]*\s*", "", clean).strip()

    for group, section in ALL_STATUTE_SECTIONS:
        if clean_no_num == section or clean == section:
            return group, section
        # Partial match for longer headings
        if len(section) > 10 and section in clean:
            return group, section
    return None


def parse_statutes(pages: dict) -> dict:
    """
    Parses IIU Statutes PDF into structured dict:
    {
        "IIU STATUTES 2006": {
            "FACULTIES": "text...",
            "DEAN": "text...",
            ...
        },
        "IIU PENSION STATUTES 2004": {...},
        ...
    }
    """
    print("\n[INFO] Parsing IIU Statutes...")

    full_text = ""
    for pnum, text in pages.items():
        full_text += f"\n\n--- PAGE {pnum} ---\n\n{text}"

    structured = {}
    current_group = "IIU STATUTES 2006"
    current_section = "Introduction"
    buffer = []

    def flush():
        content = " ".join(buffer).strip()
        if content:
            if current_group not in structured:
                structured[current_group] = {}
            existing = structured[current_group].get(current_section, "")
            structured[current_group][current_section] = (existing + " " + content).strip()

    for raw_line in full_text.split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("---"):
            continue

        # Check for statute version
        version = detect_statute_version(line)
        if version:
            flush()
            buffer = []
            current_group = version
            current_section = "Overview"
            continue

        # Check for section heading
        sec = detect_statute_section(line)
        if sec:
            flush()
            buffer = []
            current_group, current_section = sec
            continue

        buffer.append(line)

    flush()
    print(f"[INFO] Statute groups found: {list(structured.keys())}")
    return structured


# ══════════════════════════════════════════════════════════════════
#  SECTION 4: DATA CLEANER
# ══════════════════════════════════════════════════════════════════

def clean_text(text: str) -> str:
    """Cleans extracted text: removes extra spaces, page numbers, OCR artifacts."""
    # Remove page number lines like "--- PAGE 5 ---"
    text = re.sub(r"---\s*PAGE\s*\d+\s*---", "", text)
    # Remove standalone numbers (page numbers)
    text = re.sub(r"^\s*\d{1,3}\s*$", "", text, flags=re.MULTILINE)
    # Remove repeated dashes/tildes (OCR artifacts)
    text = re.sub(r"[~\-]{3,}", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_structured(data: dict) -> dict:
    """Recursively clean all text values in a structured dict."""
    if isinstance(data, dict):
        return {k: clean_structured(v) for k, v in data.items()}
    elif isinstance(data, str):
        return clean_text(data)
    return data


# ══════════════════════════════════════════════════════════════════
#  SECTION 5: EXPORT FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def export_json(data: dict, output_path: str):
    """Saves structured data as formatted JSON."""
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"[SAVED] JSON → {output_path}")


def export_txt(data: dict, output_path: str):
    """
    Saves structured data as a readable text file with clear headings.
    Format:
    ═══════════════════════════
    HEADING
    ═══════════════════════════
    Sub-heading
    ─────────────
    text...
    """
    lines = []
    for heading, content in data.items():
        lines.append("\n" + "═" * 60)
        lines.append(f"  {heading.upper()}")
        lines.append("═" * 60)

        if isinstance(content, dict):
            for sub, text in content.items():
                lines.append(f"\n{'─' * 40}")
                lines.append(f"  {sub}")
                lines.append("─" * 40)
                if isinstance(text, dict):
                    # For policy compendium nested structure
                    for k, v in text.items():
                        lines.append(f"\n  [{k}]\n  {v}\n")
                else:
                    lines.append(f"  {text}\n")
        else:
            lines.append(f"  {content}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[SAVED] TXT  → {output_path}")


def export_markdown(data: dict, output_path: str):
    """Saves structured data as a Markdown file."""
    lines = []
    for heading, content in data.items():
        lines.append(f"\n# {heading}\n")
        if isinstance(content, dict):
            for sub, text in content.items():
                lines.append(f"\n## {sub}\n")
                if isinstance(text, dict):
                    for k, v in text.items():
                        lines.append(f"\n### {k}\n\n{v}\n")
                else:
                    lines.append(f"{text}\n")
        else:
            lines.append(f"{content}\n")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[SAVED] MD   → {output_path}")


# ══════════════════════════════════════════════════════════════════
#  SECTION 6: SUMMARY / STATISTICS
# ══════════════════════════════════════════════════════════════════

def print_summary(data: dict, label: str):
    print(f"\n{'='*60}")
    print(f"  SUMMARY: {label}")
    print(f"{'='*60}")
    total_sections = 0
    total_words = 0
    for heading, content in data.items():
        if isinstance(content, dict):
            n = len(content)
            words = sum(len(str(v).split()) for v in content.values())
        else:
            n = 1
            words = len(str(content).split())
        total_sections += n
        total_words += words
        print(f"  {heading[:50]:.<50} {n:>3} section(s), ~{words:>6} words")
    print(f"{'─'*60}")
    print(f"  TOTAL: {total_sections} sections, ~{total_words} words")
    print(f"{'='*60}\n")


# ══════════════════════════════════════════════════════════════════
#  SECTION 7: NLP HELPER FUNCTIONS (for FYP BI Layer)
# ══════════════════════════════════════════════════════════════════

def search_across_documents(all_data: dict, keyword: str) -> list:
    """
    Searches for a keyword across all parsed documents.
    Returns list of (document, heading, section, snippet).
    
    Usage:
        results = search_across_documents(all_data, "admission")
        for r in results:
            print(r)
    """
    results = []
    keyword_lower = keyword.lower()

    for doc_name, doc_data in all_data.items():
        if isinstance(doc_data, dict):
            for heading, sections in doc_data.items():
                if isinstance(sections, dict):
                    for section, text in sections.items():
                        text_str = str(text)
                        if keyword_lower in text_str.lower():
                            # Get snippet around keyword
                            idx = text_str.lower().find(keyword_lower)
                            start = max(0, idx - 80)
                            end = min(len(text_str), idx + 120)
                            snippet = "..." + text_str[start:end] + "..."
                            results.append({
                                "document": doc_name,
                                "heading": heading,
                                "section": section,
                                "snippet": snippet
                            })
                elif isinstance(sections, str):
                    if keyword_lower in sections.lower():
                        idx = sections.lower().find(keyword_lower)
                        start = max(0, idx - 80)
                        end = min(len(sections), idx + 120)
                        snippet = "..." + sections[start:end] + "..."
                        results.append({
                            "document": doc_name,
                            "heading": heading,
                            "section": "—",
                            "snippet": snippet
                        })
    return results


def get_section(all_data: dict, doc_name: str, heading: str, section: str = None) -> str:
    """
    Retrieves specific section text from parsed data.
    
    Usage:
        text = get_section(all_data, "STATUTES", "IIU STATUTES 2006", "FACULTIES")
    """
    doc = all_data.get(doc_name, {})
    heading_data = doc.get(heading, {})
    if section is None:
        if isinstance(heading_data, str):
            return heading_data
        return json.dumps(heading_data, indent=2)
    if isinstance(heading_data, dict):
        return heading_data.get(section, "Section not found.")
    return heading_data


def build_qa_dataset(all_data: dict) -> list:
    """
    Builds a simple Q&A style dataset from the structured data.
    Useful for training/fine-tuning NLP models.
    
    Returns list of {"question": ..., "answer": ..., "source": ...}
    """
    qa = []
    for doc_name, doc_data in all_data.items():
        if isinstance(doc_data, dict):
            for heading, sections in doc_data.items():
                if isinstance(sections, dict):
                    for section, text in sections.items():
                        if len(str(text)) > 50:
                            q = f"What does {section} say under {heading}?"
                            qa.append({
                                "question": q,
                                "answer": str(text)[:500],
                                "source": f"{doc_name} > {heading} > {section}"
                            })
    return qa


# ══════════════════════════════════════════════════════════════════
#  SECTION 8: MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════

def main():
    print("\n" + "█" * 60)
    print("  IIU PDF EXTRACTOR — FYP: NL for Business Intelligence")
    print("█" * 60)

    # ── File paths ──────────────────────────────────────────────
    # Update these paths if running locally
    PDF_POLICY = "Policy-Compendium-2020-2023-01012024.pdf"
    PDF_STATUTES = "OCR-IIU-STATUTES-2.pdf"

    # Check if files exist; if not, show instructions
    for path in [PDF_POLICY, PDF_STATUTES]:
        if not os.path.exists(path):
            print(f"\n[WARNING] File not found: {path}")
            print(f"   → Place the PDF in the same folder as this script,")
            print(f"     OR update the path variable at the top of main()")

    output_dir = "iiu_extracted_data"
    os.makedirs(output_dir, exist_ok=True)

    all_data = {}

    # ── Process Policy Compendium ────────────────────────────────
    if os.path.exists(PDF_POLICY):
        print(f"\n{'─'*60}")
        print("  Processing: Policy Compendium")
        print("─" * 60)
        policy_pages = smart_extract(PDF_POLICY)
        policy_structured = parse_policy_compendium(policy_pages)
        policy_structured = clean_structured(policy_structured)
        all_data["POLICY_COMPENDIUM"] = policy_structured

        print_summary(policy_structured, "Policy Compendium 2020-2023")

        export_json(policy_structured, f"{output_dir}/policy_compendium.json")
        export_txt(policy_structured,  f"{output_dir}/policy_compendium.txt")
        export_markdown(policy_structured, f"{output_dir}/policy_compendium.md")
    else:
        print(f"\n[SKIP] Policy Compendium not found at: {PDF_POLICY}")

    # ── Process IIU Statutes ─────────────────────────────────────
    if os.path.exists(PDF_STATUTES):
        print(f"\n{'─'*60}")
        print("  Processing: IIU Statutes")
        print("─" * 60)
        statutes_pages = smart_extract(PDF_STATUTES)
        statutes_structured = parse_statutes(statutes_pages)
        statutes_structured = clean_structured(statutes_structured)
        all_data["IIU_STATUTES"] = statutes_structured

        print_summary(statutes_structured, "IIU Statutes")

        export_json(statutes_structured, f"{output_dir}/iiu_statutes.json")
        export_txt(statutes_structured,  f"{output_dir}/iiu_statutes.txt")
        export_markdown(statutes_structured, f"{output_dir}/iiu_statutes.md")
    else:
        print(f"\n[SKIP] IIU Statutes not found at: {PDF_STATUTES}")

    # ── Save Combined Dataset ────────────────────────────────────
    if all_data:
        export_json(all_data, f"{output_dir}/combined_iiu_data.json")

        # Build Q&A dataset for NLP/BI layer
        qa_dataset = build_qa_dataset(all_data)
        export_json(qa_dataset, f"{output_dir}/qa_dataset.json")
        print(f"\n[INFO] Q&A pairs generated: {len(qa_dataset)}")

    # ── Demo: Keyword Search ─────────────────────────────────────
    if all_data:
        print("\n" + "─" * 60)
        print("  DEMO: Keyword Search")
        print("─" * 60)

        test_keywords = ["admission", "pension", "leave", "faculty", "discipline"]
        for kw in test_keywords:
            results = search_across_documents(all_data, kw)
            print(f"\n  Keyword: '{kw}' → {len(results)} match(es)")
            for r in results[:2]:  # show first 2 results only
                print(f"    [{r['document']}] {r['heading']} > {r['section']}")
                print(f"    {r['snippet'][:100]}...")

    print("\n" + "█" * 60)
    print("  EXTRACTION COMPLETE")
    print(f"  Output folder: {os.path.abspath(output_dir)}/")
    print("  Files generated:")
    print("    ✓ policy_compendium.json / .txt / .md")
    print("    ✓ iiu_statutes.json / .txt / .md")
    print("    ✓ combined_iiu_data.json")
    print("    ✓ qa_dataset.json  (for NLP model training)")
    print("█" * 60 + "\n")


# ══════════════════════════════════════════════════════════════════
#  SECTION 9: STANDALONE DEMO (runs on built-in sample data)
#  — Use this to test WITHOUT the actual PDFs —
# ══════════════════════════════════════════════════════════════════

DEMO_STATUTES_SAMPLE = {
    1: """THE IIU STATUTES-2006
FACULTIES:-
1.1 The University shall have the following Faculties:
i) The Faculty of Islamic Studies (Usuluddin);
ii) The Faculty of Shariah and Law;
iii) The Faculty of Management Sciences;
iv) The Faculty of Education;
v) The Faculty of Social Sciences;
1.2 Each Faculty shall have a Board of Faculty.
DEAN:
2.1 There shall be a Dean of each Faculty.
2.2 The Dean shall be appointed by the Rector for three years.
TEACHING DEPARTMENTS:-
3.1 There shall be a Teaching Department for each subject.
""",
    2: """STUDENTS DISCIPLINE COMMITTEE:
12.1 There shall be a Student Discipline Committee.
12.5 The functions shall be to deal with all cases of student discipline.
BUDGET AND ACCOUNTS:
14.1 There shall be a common Fund of the University.
AUDIT:
15.1 There shall be an Internal Audit of the University.
THE IIU STATUTES-1987
PART I
SERVICE STATUTES
DEFINITIONS
1. In these Statutes the following expressions apply:
i) Ad-hoc Appointment means temporary appointment.
PROBATION
9. All appointments shall be made on probation for 2 years.
PART II
LEAVE STATUTES
CASUAL LEAVE
Employees shall be entitled to 10 and 20 days casual leave.
MATERNITY LEAVE
Maternity leave may be granted on full pay for 90 days.
PART III
EFFICIENCY & DISCIPLINE STATUTES
GROUNDS FOR PENALTY
Where an employee is inefficient or guilty of misconduct.
PENALTIES
Minor: Censure, withholding increment.
Major: Dismissal, removal, compulsory retirement.
""",
}

DEMO_POLICY_SAMPLE = {
    1: """ADMISSION POLICY
1. Eligibility
Students must have at least 60% marks in intermediate.
1.1 International students must submit equivalence certificate.
2. Documents Required
CNIC, Matric certificate, Intermediate certificate.
FEE POLICY
1. General
Fee is to be paid before the start of every semester.
2. Late Fee
Late fee of Rs. 500 per day after the due date.
EXAMINATION POLICY
1. Attendance
Minimum 75% attendance is required to appear in exams.
2. Grading
Grades are awarded on relative grading system.
""",
}


def run_demo():
    """Run extraction on demo data (no PDF files needed)."""
    print("\n" + "▓" * 60)
    print("  DEMO MODE — Using built-in sample data")
    print("▓" * 60)

    output_dir = "iiu_extracted_data_demo"
    os.makedirs(output_dir, exist_ok=True)

    # Parse statutes demo data
    stat_data = parse_statutes(DEMO_STATUTES_SAMPLE)
    stat_data = clean_structured(stat_data)
    print_summary(stat_data, "IIU Statutes [DEMO]")
    export_json(stat_data, f"{output_dir}/statutes_demo.json")
    export_txt(stat_data,  f"{output_dir}/statutes_demo.txt")
    export_markdown(stat_data, f"{output_dir}/statutes_demo.md")

    # Parse policy demo data
    pol_data = parse_policy_compendium(DEMO_POLICY_SAMPLE)
    pol_data = clean_structured(pol_data)
    print_summary(pol_data, "Policy Compendium [DEMO]")
    export_json(pol_data, f"{output_dir}/policy_demo.json")
    export_txt(pol_data,  f"{output_dir}/policy_demo.txt")
    export_markdown(pol_data, f"{output_dir}/policy_demo.md")

    # Combined
    all_data = {"POLICY_COMPENDIUM": pol_data, "IIU_STATUTES": stat_data}
    export_json(all_data, f"{output_dir}/combined_demo.json")

    qa = build_qa_dataset(all_data)
    export_json(qa, f"{output_dir}/qa_demo.json")
    print(f"\n[INFO] Q&A pairs: {len(qa)}")

    # Search demo
    print("\n  Search Demo → keyword: 'leave'")
    results = search_across_documents(all_data, "leave")
    for r in results[:3]:
        print(f"  [{r['document']}] {r['heading']} > {r['section']}")

    print(f"\n[DONE] Demo output in: {os.path.abspath(output_dir)}/\n")


# ══════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        # Run demo mode: python iiu_pdf_extractor.py --demo
        run_demo()
    else:
        # Run full pipeline with actual PDFs
        main()

        # If PDFs not found, automatically run demo
        if not (os.path.exists("Policy-Compendium-2020-2023-01012024.pdf") or
                os.path.exists("OCR-IIU-STATUTES-2.pdf")):
            print("\n[NOTE] PDFs not found locally. Running DEMO mode...\n")
            run_demo()
