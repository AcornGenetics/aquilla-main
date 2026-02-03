#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
INPUT="$BASE_DIR/pcr_curve_analysis.md"
OUTPUT="$BASE_DIR/pcr_curve_analysis.pdf"
HTML_OUTPUT="$BASE_DIR/pcr_curve_analysis.html"

if ! command -v pandoc >/dev/null 2>&1; then
  echo "pandoc is required. Install it, then rerun this script." >&2
  exit 1
fi

PDF_ENGINE="${PDF_ENGINE:-}"
if [[ -z "$PDF_ENGINE" ]]; then
  for engine in pdflatex xelatex lualatex wkhtmltopdf weasyprint; do
    if command -v "$engine" >/dev/null 2>&1; then
      PDF_ENGINE="$engine"
      break
    fi
  done
fi

if [[ -z "$PDF_ENGINE" ]]; then
  pandoc "$INPUT" -o "$HTML_OUTPUT"
  echo "No PDF engine found. Wrote $HTML_OUTPUT instead." >&2
  echo "Open the HTML file in a browser and Print to PDF." >&2
  exit 0
fi

pandoc "$INPUT" -o "$OUTPUT" --pdf-engine="$PDF_ENGINE"
echo "Wrote $OUTPUT (engine: $PDF_ENGINE)"
