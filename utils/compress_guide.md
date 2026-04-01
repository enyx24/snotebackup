# Samsung Notes .sdocx Compression Guide

## 1. What Needs to Be Compressed

A `.sdocx` file contains the following required members in a strict order:

1. **media/mediaInfo.dat** — metadata file listing all media entries
2. **media/** folder — all payload files (audio, PDF, images)
   - `*.m4a` (audio)
   - `*.pdf` (documents)
   - `*.spi` (page images)
3. **\*.page** — page content files (one per page, binary format)
4. **pageIdInfo.dat** — page ID mapping file
5. **note.note** — note metadata and content (binary)
6. **end_tag.bin** — binary trailer (special Samsung marker)

## 2. Compression Method Rules

| File Type | Method | Level | Notes |
|-----------|--------|-------|-------|
| media/*.m4a | STORE | — | No compression (already compressed) |
| media/*.pdf | STORE | — | No compression (already compressed) |
| media/*.spi | STORE | — | No compression (binary image data) |
| media/mediaInfo.dat | DEFLATE | 1 | Compressed at level 1 |
| *.page | DEFLATE | 1 | Compressed at level 1 |
| pageIdInfo.dat | DEFLATE | 1 | Compressed at level 1 |
| note.note | DEFLATE | 1 | Compressed at level 1 |
| end_tag.bin | NOT ZIPPED | — | Appended raw after EOCD |

**Critical:** Using deflate level `9` produces incompatible stream sizes; level `1` reproduces Samsung's byte-for-byte.

## 3. Differences from Normal ZIP

### Entry Order Matters
Normal ZIP readers use central directory (any order). Samsung Notes reads **local file headers in sequence**, so order must be:
1. `media/mediaInfo.dat`
2. `media/*` (sorted alphabetically by filename)
3. `*.page` (sorted alphabetically)
4. `pageIdInfo.dat`
5. `note.note`
6. `end_tag.bin`

### ZIP Header Fields
Samsung expects specific metadata that differs from Python's defaults:

| Field | Value | Reason |
|-------|-------|--------|
| DOS date/time | (1980, 1, 0, 0, 0, 0) | Samsung canonical epoch |
| Flag bits | 0x0800 (STORED) or 0x0806 (DEFLATE) | Indicates no data descriptor |
| Version made by | 0 | Strict compatibility |
| External attributes | 0x0 | No file system metadata |

### Post-EOCD Trailer
After the normal ZIP EOCD (End of Central Directory):
```
[ZIP LOCAL HEADERS]
[ZIP CENTRAL DIRECTORY]
[ZIP EOCD - 22 bytes]
[end_tag.bin - 148 bytes raw, NOT ZIPPED]
```

The raw `end_tag.bin` content is appended directly after EOCD without any ZIP wrapper.

### Media File Ordering
Instead of naive lexical sorting, derive order from `mediaInfo.dat` byte positions:
- Search for media filenames inside `mediaInfo.dat` (UTF-8, UTF-16LE, UTF-16BE)
- Sort by first occurrence position
- Preserves Samsung's original ordering intent

### No Data Descriptors
Flag bit 3 must be `0` (not set) for all entries. All CRC, compressed size, and uncompressed size must be in local and central headers, not in optional descriptors.

---

**Summary:** `.sdocx` is a ZIP protocol wrapper enforcing precise serialization order, header metadata, compression rules, and a non-standard trailing payload. Tools must respect all three categories above to achieve Samsung Notes import compatibility.
