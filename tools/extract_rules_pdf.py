from __future__ import annotations

import argparse
import sys
from pathlib import Path


def import_pdfplumber():
    try:
        import pdfplumber

        return pdfplumber
    except ModuleNotFoundError:
        local_target = Path(".tmp_pdf_extract")
        if local_target.exists():
            sys.path.insert(0, str(local_target))
            import pdfplumber

            return pdfplumber
        raise SystemExit(
            "pdfplumber is required. Install it with:\n"
            "  python -m pip install --target .tmp_pdf_extract pdfplumber"
        )


def extract_rules(pdf_path: Path, output_path: Path) -> None:
    pdfplumber = import_pdfplumber()
    lines = [
        "StarShot rules text extraction",
        f"Source: {pdf_path.as_posix()}",
        f"Extractor: pdfplumber {pdfplumber.__version__}",
        "",
        "",
    ]

    with pdfplumber.open(str(pdf_path)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            lines.append(f"===== PAGE {page_number} =====")

            text = page.extract_text(x_tolerance=1, y_tolerance=3) or ""
            lines.extend(text.splitlines())

            tables = page.extract_tables()
            if tables:
                lines.append("")
                lines.append(f"----- TABLES DETECTED ON PAGE {page_number} -----")
                for table_index, table in enumerate(tables, start=1):
                    lines.append(f"[Table {page_number}.{table_index}]")
                    for row in table:
                        cells = [(cell or "").replace("\n", " ").strip() for cell in row]
                        lines.append(" | ".join(cells))
                    lines.append("")

            lines.append("")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract StarShot rules PDF text.")
    parser.add_argument(
        "pdf",
        nargs="?",
        default="docs/rules/rules_0.1.pdf",
        type=Path,
        help="Path to the source rules PDF.",
    )
    parser.add_argument(
        "output",
        nargs="?",
        default="docs/rules/rules_0.1.txt",
        type=Path,
        help="Path for the extracted text file.",
    )
    args = parser.parse_args()

    extract_rules(args.pdf, args.output)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
