import argparse
import io
import json
import os
import re
import zipfile


def _require_pypdf():
    try:
        from pypdf import PdfReader
    except Exception as exc:
        raise RuntimeError(
            "Missing dependency 'pypdf'. Install with: py -3 -m pip install pypdf"
        ) from exc
    return PdfReader


def _normalize_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_pdf_bytes(pdf_bytes):
    PdfReader = _require_pypdf()
    reader = PdfReader(io.BytesIO(pdf_bytes))

    pages = []
    all_text = []
    for index, page in enumerate(reader.pages, start=1):
        raw = page.extract_text() or ""
        text = _normalize_text(raw)
        pages.append({"page": index, "text": text})
        if text:
            all_text.append(text)

    return {
        "page_count": len(reader.pages),
        "non_empty_pages": sum(1 for page in pages if page["text"]),
        "pages": pages,
        "plain_text": "\n".join(all_text),
    }


def extract_pdf_text(input_path):
    lower = input_path.lower()
    if lower.endswith(".pdf"):
        with open(input_path, "rb") as source:
            payload = source.read()
        result = _extract_pdf_bytes(payload)
        return {
            "input": os.path.abspath(input_path),
            "type": "pdf",
            "pdf_count": 1,
            "records": [
                {
                    "source": os.path.basename(input_path),
                    **result,
                }
            ],
            "plain_text": result["plain_text"],
        }

    if lower.endswith(".sdocx"):
        records = []
        all_text = []
        with zipfile.ZipFile(input_path, "r") as archive:
            for name in archive.namelist():
                if not name.lower().endswith(".pdf"):
                    continue
                pdf_result = _extract_pdf_bytes(archive.read(name))
                records.append({"source": name, **pdf_result})
                if pdf_result["plain_text"]:
                    all_text.append(pdf_result["plain_text"])

        return {
            "input": os.path.abspath(input_path),
            "type": "sdocx",
            "pdf_count": len(records),
            "records": records,
            "plain_text": "\n".join(all_text),
        }

    raise ValueError("Input must be a .pdf or .sdocx file")


def _resolve_output_paths(input_path, out_prefix=None, json_out=None, text_out=None):
    if out_prefix:
        return f"{out_prefix}.json", f"{out_prefix}.txt"

    input_name = os.path.basename(input_path)
    stem, _ = os.path.splitext(input_name)
    base = os.path.join(os.getcwd(), f"{stem}_pdf")
    return json_out or f"{base}.json", text_out or f"{base}.txt"


def _write_outputs(result, json_path, text_path):
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(result, jf, ensure_ascii=False, indent=2)

    with open(text_path, "w", encoding="utf-8") as tf:
        tf.write(result["plain_text"])
        tf.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Simple PDF text extractor (no OCR)")
    parser.add_argument("input", help="Path to .pdf or .sdocx")
    parser.add_argument("--out-prefix", help="Output prefix without extension")
    parser.add_argument("--json-out", help="Explicit JSON output path")
    parser.add_argument("--text-out", help="Explicit text output path")
    args = parser.parse_args()

    result = extract_pdf_text(args.input)
    json_path, text_path = _resolve_output_paths(
        args.input,
        out_prefix=args.out_prefix,
        json_out=args.json_out,
        text_out=args.text_out,
    )
    _write_outputs(result, json_path, text_path)

    print(f"Extracted text from {result['pdf_count']} PDF file(s)")
    print(f"JSON: {json_path}")
    print(f"TEXT: {text_path}")


if __name__ == "__main__":
    main()
