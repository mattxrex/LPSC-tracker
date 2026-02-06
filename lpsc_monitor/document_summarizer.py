"""
Document Summarizer for LPSC Docket Documents

This module sends downloaded docket PDFs to the Claude API (Haiku model)
and gets structured summaries back. Summaries are stored in the database
so each document is only summarized once.

How it works:
1. Find documents in the database that don't have summaries yet
2. For each document, send the PDF to Claude with a tailored prompt
3. Claude returns a structured summary (Action, Parties, Key Details, Status)
4. Store the summary in the database

For very large PDFs (estimated >150k tokens), it falls back to:
- Extracting text with pdfplumber (same library used for bulletin parsing)
- Splitting into chunks
- Summarizing each chunk, then combining with a final summary call
"""

import base64
import os
import time
from pathlib import Path
from typing import Optional

import anthropic
import pdfplumber

from config import (
    CLAUDE_MODEL, CLAUDE_MAX_TOKENS, CLAUDE_DELAY_BETWEEN_CALLS,
    CLAUDE_TOKENS_PER_MB, CLAUDE_MAX_INPUT_TOKENS,
    CLAUDE_CHUNK_MAX_TOKENS, CLAUDE_CHARS_PER_TOKEN,
    log
)
import database as db


# =============================================================================
# DOCUMENT TYPE FOCUS AREAS
# =============================================================================

# Different document types need different summarization focus.
# This dict maps document types (from the LPSC portal) to what the
# summarizer should pay special attention to.
TYPE_FOCUS = {
    "Order": "regulatory decisions, directives, deadlines, and compliance requirements",
    "Application": "what is being requested, by whom, the justification, and financial impacts",
    "Report": "findings, data, conclusions, and recommendations",
    "Miscellaneous": "the purpose of the filing and any actions requested",
    "Correspondence": "the sender, recipient, topic, and any requests or responses",
    "Testimony": "the witness, their position, key arguments, and supporting evidence",
}


# =============================================================================
# PROMPT BUILDING
# =============================================================================

def build_prompt(doc_type: str, docket_number: str, docket_title: str) -> str:
    """
    Build a summarization prompt tailored to the document type.

    The prompt asks Claude for a structured summary with consistent sections,
    but adjusts the focus based on what kind of document it is (Order vs.
    Application vs. Report, etc.).

    Args:
        doc_type: Document type from the LPSC portal (e.g., "Order")
        docket_number: The docket number (e.g., "U-36625")
        docket_title: The docket title from the bulletin

    Returns:
        The prompt string to send to Claude
    """
    # Look up the focus area for this document type, with a generic fallback
    focus = TYPE_FOCUS.get(doc_type, "the key facts, decisions, and next steps")

    return f"""Summarize this Louisiana Public Service Commission (LPSC) document.

Context:
- Docket: {docket_number}
- Docket title: {docket_title}
- Document type: {doc_type}

Focus especially on: {focus}

Provide your summary in this format:

**Action:** [One sentence: what this document does or decides]

**Parties:** [Who is involved — utilities, intervenors, LPSC staff, etc.]

**Key Details:**
- [Most important point]
- [Second most important point]
- [Additional points as needed, but keep it concise]

**Status/Next Steps:** [Deadlines, required actions, or what happens next]

Keep the summary concise but complete — aim for 150-300 words."""


# =============================================================================
# SUMMARIZATION FUNCTIONS
# =============================================================================

def summarize_document(pdf_path: str, doc_type: str, docket_number: str,
                       docket_title: str) -> Optional[str]:
    """
    Summarize a single PDF document using the Claude API.

    Sends the PDF as a base64-encoded document to Claude's vision/PDF
    capability. If the file is estimated to be too large (>150k tokens),
    falls back to text extraction and chunking.

    Uses anthropic.Anthropic(max_retries=3) for automatic retry on
    rate limit (429) and server (5xx) errors.

    Args:
        pdf_path: Path to the PDF file on disk
        doc_type: Document type (e.g., "Order", "Application")
        docket_number: Docket number (e.g., "U-36625")
        docket_title: Docket title from the bulletin

    Returns:
        Summary text, or None if summarization failed
    """
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        print(f"    WARNING: PDF not found: {pdf_path}")
        return None

    # Estimate token count from file size
    file_size_mb = pdf_file.stat().st_size / (1024 * 1024)
    estimated_tokens = int(file_size_mb * CLAUDE_TOKENS_PER_MB)
    log(f"PDF size: {file_size_mb:.1f} MB, estimated ~{estimated_tokens:,} tokens")

    # If too large, use the chunking fallback
    if estimated_tokens > CLAUDE_MAX_INPUT_TOKENS:
        print(f"    Large document ({file_size_mb:.1f} MB) — using text chunking")
        return _summarize_large_document(pdf_path, doc_type, docket_number, docket_title)

    # Read and encode the PDF
    pdf_data = pdf_file.read_bytes()
    pdf_base64 = base64.standard_b64encode(pdf_data).decode("utf-8")

    # Build the prompt
    prompt = build_prompt(doc_type, docket_number, docket_title)

    # Create the API client with automatic retry (handles 429 and 5xx)
    client = anthropic.Anthropic(max_retries=3)

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_base64,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )

        # Extract the text from the response
        summary = message.content[0].text
        log(f"API response: {message.usage.input_tokens} input, "
            f"{message.usage.output_tokens} output tokens")
        return summary

    except anthropic.APIError as e:
        print(f"    ERROR: Claude API error: {e}")
        return None


def _summarize_large_document(pdf_path: str, doc_type: str,
                              docket_number: str, docket_title: str) -> Optional[str]:
    """
    Fallback for PDFs that are too large to send as a single API call.

    Strategy:
    1. Extract all text from the PDF using pdfplumber
    2. Split the text into chunks that fit within token limits
    3. Summarize each chunk separately
    4. Combine chunk summaries with one final API call

    Args:
        pdf_path: Path to the PDF file
        doc_type: Document type
        docket_number: Docket number
        docket_title: Docket title

    Returns:
        Combined summary text, or None if it failed
    """
    # Step 1: Extract text
    log("Extracting text from large PDF with pdfplumber...")
    full_text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
    except Exception as e:
        print(f"    ERROR: Could not extract text from PDF: {e}")
        return None

    if not full_text.strip():
        print("    WARNING: No text extracted (may be a scanned document)")
        return None

    log(f"Extracted {len(full_text):,} characters from PDF")

    # Step 2: Split into chunks
    max_chars_per_chunk = CLAUDE_CHUNK_MAX_TOKENS * CLAUDE_CHARS_PER_TOKEN
    chunks = []
    for i in range(0, len(full_text), max_chars_per_chunk):
        chunks.append(full_text[i:i + max_chars_per_chunk])

    log(f"Split into {len(chunks)} chunk(s)")

    # Step 3: Summarize each chunk
    client = anthropic.Anthropic(max_retries=3)
    chunk_summaries = []

    for i, chunk in enumerate(chunks):
        log(f"Summarizing chunk {i+1}/{len(chunks)}...")

        chunk_prompt = (
            f"This is part {i+1} of {len(chunks)} of an LPSC document.\n"
            f"Docket: {docket_number} — {docket_title}\n"
            f"Document type: {doc_type}\n\n"
            f"Summarize the key points from this section:\n\n{chunk}"
        )

        try:
            message = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                messages=[{"role": "user", "content": chunk_prompt}],
            )
            chunk_summaries.append(message.content[0].text)
            time.sleep(CLAUDE_DELAY_BETWEEN_CALLS)
        except anthropic.APIError as e:
            print(f"    ERROR on chunk {i+1}: {e}")
            chunk_summaries.append(f"[Chunk {i+1} could not be summarized]")

    # Step 4: Combine chunk summaries
    combined = "\n\n---\n\n".join(chunk_summaries)
    final_prompt = build_prompt(doc_type, docket_number, docket_title)
    final_prompt += (
        f"\n\nBelow are summaries of individual sections of this document. "
        f"Combine them into a single coherent summary using the format above.\n\n"
        f"{combined}"
    )

    try:
        message = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=CLAUDE_MAX_TOKENS,
            messages=[{"role": "user", "content": final_prompt}],
        )
        return message.content[0].text
    except anthropic.APIError as e:
        print(f"    ERROR combining summaries: {e}")
        # Return the chunk summaries as a fallback
        return combined


# =============================================================================
# ORCHESTRATOR
# =============================================================================

def summarize_documents_for_bulletin(bulletin_number: int = None):
    """
    Main orchestrator: summarize all unsummarized documents for a bulletin.

    If no bulletin_number is given, uses the latest bulletin in the database.

    Steps:
    1. Look up the bulletin
    2. Find documents that need summaries
    3. Summarize each one with a delay between calls
    4. Store results in the database
    5. Print progress and a final summary

    Args:
        bulletin_number: Specific bulletin number, or None for latest
    """
    db.init_database()

    # Step 1: Find the bulletin
    if bulletin_number:
        bulletin = db.get_bulletin(bulletin_number)
        if not bulletin:
            print(f"ERROR: Bulletin #{bulletin_number} not found in database.")
            print("Process it first with: python main.py check")
            return
    else:
        all_bulletins = db.get_all_bulletins()
        if not all_bulletins:
            print("ERROR: No bulletins in database. Run 'python main.py check' first.")
            return
        bulletin = all_bulletins[0]
        bulletin_number = bulletin['number']

    print(f"\n{'='*60}")
    print(f"Summarizing Documents for Bulletin #{bulletin_number}")
    print(f"{'='*60}")

    # Step 2: Get unsummarized documents
    documents = db.get_unsummarized_documents(bulletin['id'])

    if not documents:
        print("\nNo unsummarized documents found.")
        return

    print(f"Found {len(documents)} document(s) to summarize.\n")

    # Step 3: Summarize each document
    success_count = 0
    error_count = 0

    for i, doc in enumerate(documents):
        doc_name = Path(doc['pdf_path']).name
        print(f"[{i+1}/{len(documents)}] {doc['docket_number']} — {doc_name}")
        print(f"  Type: {doc['document_type'] or 'Unknown'}")

        summary = summarize_document(
            pdf_path=doc['pdf_path'],
            doc_type=doc['document_type'] or 'Miscellaneous',
            docket_number=doc['docket_number'],
            docket_title=doc['docket_title'] or '',
        )

        if summary:
            # Step 4: Store the summary
            db.update_document_summary(doc['id'], summary)
            success_count += 1
            # Print first line of summary as preview
            first_line = summary.split('\n')[0]
            print(f"  Summary: {first_line[:80]}")
        else:
            error_count += 1
            print(f"  FAILED to summarize")

        # Delay between calls to avoid rate limits
        if i < len(documents) - 1:
            time.sleep(CLAUDE_DELAY_BETWEEN_CALLS)

    # Step 5: Print summary
    print(f"\n{'='*60}")
    print("SUMMARIZATION COMPLETE")
    print(f"{'='*60}")
    print(f"Summarized:  {success_count} document(s)")
    print(f"Errors:      {error_count}")
    print(f"{'='*60}")
