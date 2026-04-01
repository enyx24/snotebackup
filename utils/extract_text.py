import argparse
import bz2
import gzip
import hashlib
import io
import json
import lzma
import os
import re
import zlib
import zipfile


ASCII_RUN_PATTERN = re.compile(rb"[\x20-\x7E]{8,}")
UTF16LE_RUN_PATTERN = re.compile(rb"(?:[\x20-\x7E]\x00){6,}")
UTF16BE_RUN_PATTERN = re.compile(rb"(?:\x00[\x20-\x7E]){6,}")
UUID_PATTERN = re.compile(
    r"^\$?[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}[A-Za-z]?$"
)


def _normalize_text(text):
    text = text.replace("\x00", " ")
    text = re.sub(r"[\t\r\f\v]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_text_like(text):
    if not text:
        return False
    printable = sum(1 for c in text if c.isprintable() or c.isspace())
    ratio = printable / max(len(text), 1)
    alpha = sum(1 for c in text if c.isalpha())
    alpha_ratio = alpha / max(len(text), 1)
    return ratio >= 0.95 and alpha_ratio >= 0.2


def _is_metadata_noise(text):
    if UUID_PATTERN.match(text):
        return True
    lower = text.lower()
    if lower.startswith("/com.samsung.android"):
        return True
    if "s-pen sdk" in lower:
        return True

    words = re.findall(r"[A-Za-z]+", text)
    if len(words) < 4:
        return True

    letter_count = sum(1 for c in text if c.isalpha())
    symbol_count = sum(1 for c in text if not (c.isalnum() or c.isspace() or c in ".,!?;:'\"()-%"))
    if letter_count == 0:
        return True
    if symbol_count / max(len(text), 1) > 0.05:
        return True

    return False


def _split_candidates(text, min_length):
    raw_parts = re.split(r"\n+|\r+|\|+", text)
    chunks = []
    for part in raw_parts:
        normalized = _normalize_text(part)
        if (
            len(normalized) >= min_length
            and _is_text_like(normalized)
            and not _is_metadata_noise(normalized)
        ):
            chunks.append(normalized)
    return chunks


def _decode_with_encodings(blob, min_length):
    outputs = []
    for encoding in ("utf-8", "utf-16le", "utf-16be", "utf-32le", "utf-32be"):
        try:
            text = blob.decode(encoding)
        except UnicodeDecodeError:
            continue

        if "\x00\x00\x00" in text:
            continue

        chunks = _split_candidates(text, min_length)
        if chunks:
            outputs.append((f"decode:{encoding}", chunks, 0.95))
    return outputs


def _decompress_candidates(blob):
    queue = [(blob, "raw", 0)]
    seen = {hashlib.sha1(blob).hexdigest()}
    results = [(blob, "raw")]

    while queue:
        data, label, depth = queue.pop(0)
        if depth >= 2:
            continue

        attempts = []
        try:
            attempts.append((gzip.decompress(data), f"{label}->gzip"))
        except Exception:
            pass

        for wbits, suffix in ((zlib.MAX_WBITS, "zlib"), (-zlib.MAX_WBITS, "deflate"), (zlib.MAX_WBITS | 32, "zlib-auto")):
            try:
                attempts.append((zlib.decompress(data, wbits), f"{label}->{suffix}"))
            except Exception:
                continue

        try:
            attempts.append((bz2.decompress(data), f"{label}->bz2"))
        except Exception:
            pass

        try:
            attempts.append((lzma.decompress(data), f"{label}->lzma"))
        except Exception:
            pass

        for out_data, out_label in attempts:
            if not out_data or len(out_data) < 8:
                continue
            digest = hashlib.sha1(out_data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            results.append((out_data, out_label))
            queue.append((out_data, out_label, depth + 1))

    return results


def _extract_string_runs(blob, min_length):
    chunks = []

    for match in ASCII_RUN_PATTERN.findall(blob):
        text = _normalize_text(match.decode("ascii", errors="ignore"))
        if len(text) >= min_length and _is_text_like(text) and not _is_metadata_noise(text):
            chunks.append(("strings:ascii", text, 0.82))

    for match in UTF16LE_RUN_PATTERN.findall(blob):
        text = _normalize_text(match.decode("utf-16le", errors="ignore"))
        if len(text) >= min_length and _is_text_like(text) and not _is_metadata_noise(text):
            chunks.append(("strings:utf16le", text, 0.85))

    for match in UTF16BE_RUN_PATTERN.findall(blob):
        text = _normalize_text(match.decode("utf-16be", errors="ignore"))
        if len(text) >= min_length and _is_text_like(text) and not _is_metadata_noise(text):
            chunks.append(("strings:utf16be", text, 0.85))

    return chunks


def _extract_pdf_chunks(blob, min_length):
    try:
        from pypdf import PdfReader
    except Exception:
        return []

    try:
        reader = PdfReader(io.BytesIO(blob))
    except Exception:
        return []

    chunks = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = _normalize_text(page.extract_text() or "")
        if len(text) < min_length:
            continue
        chunks.append(
            {
                "text": text,
                "strategy": f"pdf:pypdf:page:{page_index}",
                "confidence": 0.98,
            }
        )
    return chunks


def extract_payload_text(blob, min_length=20, min_confidence=0.82):
    candidates = []
    for decompressed_blob, path_label in _decompress_candidates(blob):
        decoded_sets = _decode_with_encodings(decompressed_blob, min_length)
        for strategy, chunks, confidence in decoded_sets:
            for chunk in chunks:
                candidates.append(
                    {
                        "text": chunk,
                        "strategy": f"{path_label}:{strategy}",
                        "confidence": confidence,
                    }
                )

        for strategy, text, confidence in _extract_string_runs(decompressed_blob, min_length):
            candidates.append(
                {
                    "text": text,
                    "strategy": f"{path_label}:{strategy}",
                    "confidence": confidence,
                }
            )

    dedup = {}
    for item in candidates:
        text = item["text"]
        if item["confidence"] < min_confidence:
            continue
        prior = dedup.get(text)
        if prior is None or item["confidence"] > prior["confidence"]:
            dedup[text] = item

    return sorted(dedup.values(), key=lambda entry: (-entry["confidence"], entry["text"]))


def _collect_payloads_from_sdocx(sdocx_path, include_pdf=False):
    payloads = []
    with zipfile.ZipFile(sdocx_path, "r") as archive:
        for name in archive.namelist():
            lowered = name.lower()
            if lowered.endswith(".note"):
                payloads.append((name, "note", archive.read(name)))
            elif lowered.endswith(".page"):
                payloads.append((name, "page", archive.read(name)))
            elif include_pdf and lowered.endswith(".pdf"):
                payloads.append((name, "pdf", archive.read(name)))
    return payloads


def _collect_payloads_from_folder(folder_path, include_pdf=False):
    payloads = []
    for root, _, files in os.walk(folder_path):
        for filename in files:
            lowered = filename.lower()
            if not (lowered.endswith(".note") or lowered.endswith(".page") or (include_pdf and lowered.endswith(".pdf"))):
                continue
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, folder_path).replace("\\", "/")
            if lowered.endswith(".note"):
                payload_type = "note"
            elif lowered.endswith(".page"):
                payload_type = "page"
            else:
                payload_type = "pdf"
            with open(full_path, "rb") as source:
                payloads.append((rel_path, payload_type, source.read()))
    return payloads


def extract_from_input(input_path, min_length=20, min_confidence=0.82, include_pdf=True):
    if os.path.isdir(input_path):
        payloads = _collect_payloads_from_folder(input_path, include_pdf=include_pdf)
    elif input_path.lower().endswith(".sdocx"):
        payloads = _collect_payloads_from_sdocx(input_path, include_pdf=include_pdf)
    elif input_path.lower().endswith(".pdf"):
        with open(input_path, "rb") as source:
            payloads = [(os.path.basename(input_path), "pdf", source.read())]
    else:
        raise ValueError("Input must be a .sdocx/.pdf file or a folder containing .note/.page/.pdf files")

    records = []
    all_text = []

    for source_name, payload_type, blob in payloads:
        if payload_type == "pdf":
            chunks = [
                item
                for item in _extract_pdf_chunks(blob, min_length=min_length)
                if item["confidence"] >= min_confidence
            ]
        else:
            chunks = extract_payload_text(blob, min_length=min_length, min_confidence=min_confidence)
        if not chunks:
            continue
        records.append(
            {
                "source": source_name,
                "type": payload_type,
                "chunks": chunks,
            }
        )
        all_text.extend(chunk["text"] for chunk in chunks)

    unique_text = []
    seen = set()
    for text in all_text:
        if text in seen:
            continue
        seen.add(text)
        unique_text.append(text)

    return {
        "input": os.path.abspath(input_path),
        "file_count": len(payloads),
        "matched_files": len(records),
        "text_count": len(unique_text),
        "records": records,
        "plain_text": "\n".join(unique_text),
    }


def _resolve_output_paths(input_path, out_prefix=None, json_out=None, text_out=None):
    if out_prefix:
        return f"{out_prefix}.json", f"{out_prefix}.txt"

    input_name = os.path.basename(input_path)
    stem, _ = os.path.splitext(input_name)
    base = os.path.join(os.getcwd(), f"{stem}_extracted")
    return json_out or f"{base}.json", text_out or f"{base}.txt"


def _write_outputs(result, json_path, text_path):
    with open(json_path, "w", encoding="utf-8") as jf:
        json.dump(result, jf, ensure_ascii=False, indent=2)

    with open(text_path, "w", encoding="utf-8") as tf:
        tf.write(result["plain_text"])
        tf.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Extract essential text from Samsung Notes .sdocx/.note/.page and embedded PDF")
    parser.add_argument("input", help="Path to .sdocx/.pdf file or unpacked folder")
    parser.add_argument("--out-prefix", help="Output prefix without extension")
    parser.add_argument("--json-out", help="Explicit JSON output path")
    parser.add_argument("--text-out", help="Explicit text output path")
    parser.add_argument("--min-length", type=int, default=20, help="Minimum chunk length")
    parser.add_argument("--no-pdf", action="store_true", help="Disable PDF extraction")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.82,
        help="Minimum confidence threshold (0.0 to 1.0)",
    )
    args = parser.parse_args()

    result = extract_from_input(
        args.input,
        min_length=max(args.min_length, 8),
        min_confidence=min(max(args.min_confidence, 0.0), 1.0),
        include_pdf=not args.no_pdf,
    )

    json_path, text_path = _resolve_output_paths(
        args.input,
        out_prefix=args.out_prefix,
        json_out=args.json_out,
        text_out=args.text_out,
    )
    _write_outputs(result, json_path, text_path)

    print(f"Extracted {result['text_count']} text chunks from {result['matched_files']} files")
    print(f"JSON: {json_path}")
    print(f"TEXT: {text_path}")


if __name__ == "__main__":
    main()
