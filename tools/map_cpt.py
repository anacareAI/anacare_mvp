"""
map_cpt.py

Maps a plain-language procedure description to CPT code candidates
using the Claude API. Returns a ranked list with confidence scores.

This tool powers the /cpt-lookup API endpoint.

Usage:
    python tools/map_cpt.py "knee replacement"
    python tools/map_cpt.py --query "colonoscopy"

Output:
    JSON list of {cpt_code, label, confidence} objects, printed to stdout
    and written to .tmp/cpt_lookup_result.json
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

TMP_DIR = Path(".tmp")
OUTPUT_PATH = TMP_DIR / "cpt_lookup_result.json"

MODEL = "claude-opus-4-6"
MAX_CANDIDATES = 5

# System prompt — instructs Claude to return only CPT codes, no PHI
SYSTEM_PROMPT = """You are a medical coding assistant specializing in CPT (Current Procedural Terminology) codes.

Your task: given a plain-language medical procedure description, return the most likely CPT codes.

Rules:
- Return ONLY a JSON array. No prose, no explanation, no markdown.
- Each element must have: cpt_code (string), label (string), confidence (float 0.0-1.0)
- Sort by confidence descending
- Return at most 5 candidates
- Only include codes you are confident exist in the AMA CPT code set
- Never include patient identifiers or PHI in your response
- If the procedure is ambiguous, return all plausible CPT codes

Example output:
[
  {"cpt_code": "27447", "label": "Total knee arthroplasty", "confidence": 0.91},
  {"cpt_code": "27446", "label": "Medial compartment knee arthroplasty", "confidence": 0.61}
]"""


def lookup_cpt(procedure_query: str) -> list[dict]:
    """
    Query Claude API with a procedure description and return CPT candidates.
    Input must be a procedure description only — no patient data.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        log.error("ANTHROPIC_API_KEY not set in .env")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    log.info(f"Querying Claude API for: '{procedure_query}'")

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Procedure: {procedure_query}",
            }
        ],
    )

    raw_text = message.content[0].text.strip()
    log.debug(f"Raw API response: {raw_text}")

    # Strip markdown fences if present
    if raw_text.startswith("```"):
        lines = raw_text.split("\n")
        raw_text = "\n".join(lines[1:-1])

    try:
        candidates = json.loads(raw_text)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse Claude response as JSON: {e}")
        log.error(f"Raw response: {raw_text}")
        return []

    # Validate and sanitize output
    validated = []
    for c in candidates[:MAX_CANDIDATES]:
        cpt_code = str(c.get("cpt_code", "")).strip()
        label = str(c.get("label", "")).strip()
        try:
            confidence = float(c.get("confidence", 0))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.0

        if cpt_code and label:
            validated.append({
                "cpt_code": cpt_code,
                "label": label,
                "confidence": round(confidence, 3),
            })

    return sorted(validated, key=lambda x: x["confidence"], reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Map procedure description to CPT codes via Claude API")
    parser.add_argument("query", nargs="?", help="Procedure description")
    parser.add_argument("--query", dest="query_flag", help="Procedure description (alternative)")
    args = parser.parse_args()

    procedure_query = args.query or args.query_flag
    if not procedure_query:
        log.error("Provide a procedure description as argument or --query flag")
        parser.print_help()
        sys.exit(1)

    candidates = lookup_cpt(procedure_query)

    if not candidates:
        log.warning("No CPT candidates returned")
        sys.exit(1)

    result = {
        "query": procedure_query,
        "cpt_candidates": candidates,
    }

    TMP_DIR.mkdir(exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))
    log.info(f"Result written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
