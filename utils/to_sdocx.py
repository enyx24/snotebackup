import zipfile
import os
import struct 
from config.constants import DOS_EPOCH


def _has_note_markers(folder_path):
    marker_files = {"note.note", "end_tag.bin", "pageIdInfo.dat"}
    try:
        entries = os.listdir(folder_path)
    except OSError:
        return False

    entry_set = set(entries)
    if marker_files & entry_set:
        return True
    if any(name.endswith(".page") for name in entries):
        return True
    if "media" in entry_set and os.path.isdir(os.path.join(folder_path, "media")):
        return True
    return False


def _detect_content_root(src_folder):
    if _has_note_markers(src_folder):
        return src_folder

    try:
        entries = os.listdir(src_folder)
    except OSError:
        return src_folder

    subdirs = [name for name in entries if os.path.isdir(os.path.join(src_folder, name))]
    files = [name for name in entries if os.path.isfile(os.path.join(src_folder, name))]

    if len(subdirs) == 1 and not files:
        candidate = os.path.join(src_folder, subdirs[0])
        if _has_note_markers(candidate):
            return candidate

    return src_folder


def _build_ordered_entries(file_map):
    all_paths = set(file_map.keys())
    ordered = []

    media_info = "media/mediaInfo.dat"
    if media_info in all_paths:
        ordered.append(media_info)

    media_files = _ordered_media_files(file_map)
    ordered.extend(media_files)

    pages = sorted(path for path in all_paths if path.endswith(".page"))
    ordered.extend(pages)

    if "pageIdInfo.dat" in all_paths:
        ordered.append("pageIdInfo.dat")
    if "note.note" in all_paths:
        ordered.append("note.note")

    remaining = sorted(path for path in all_paths if path not in set(ordered) and path != "end_tag.bin")
    ordered.extend(remaining)

    if "end_tag.bin" in all_paths:
        ordered.append("end_tag.bin")

    return ordered


def _validate_required_members(file_map):
    all_paths = set(file_map.keys())

    required = ["note.note", "end_tag.bin", "pageIdInfo.dat"]
    missing = [name for name in required if name not in all_paths]
    if missing:
        raise ValueError(f"Missing required file(s): {', '.join(missing)}")

    if not any(path.endswith(".page") for path in all_paths):
        raise ValueError("Missing required .page file")

    if not any(path.startswith("media/") for path in all_paths):
        raise ValueError("Missing required media folder content")

    if "media/mediaInfo.dat" not in all_paths:
        raise ValueError("Missing required media/mediaInfo.dat")


def _compress_type_for(rel_path):
    if rel_path.startswith("media/") and rel_path != "media/mediaInfo.dat":
        return zipfile.ZIP_STORED
    return zipfile.ZIP_DEFLATED


def _target_flag_for(rel_path, compress_type):
    if compress_type == zipfile.ZIP_STORED:
        return 0x0800
    return 0x0806


def _ordered_media_files(file_map):
    media_info_key = "media/mediaInfo.dat"
    media_files = sorted(
        path for path in file_map.keys() if path.startswith("media/") and path != media_info_key
    )

    media_info_path = file_map.get(media_info_key)
    if not media_info_path or not media_files:
        return media_files

    with open(media_info_path, "rb") as source:
        media_info_bytes = source.read()

    discovered = []
    unresolved = []

    for rel_path in media_files:
        media_name = rel_path.split("/", 1)[1]
        candidates = [
            media_name.encode("utf-8"),
            media_name.encode("utf-16le"),
            media_name.encode("utf-16be"),
        ]
        positions = [media_info_bytes.find(candidate) for candidate in candidates]
        positions = [position for position in positions if position >= 0]

        if positions:
            discovered.append((min(positions), rel_path))
        else:
            unresolved.append(rel_path)

    discovered.sort(key=lambda item: (item[0], item[1]))
    unresolved.sort()
    return [item[1] for item in discovered] + unresolved


def _rewrite_zip_headers(zip_path, entry_flags):
    local_sig = b"PK\x03\x04"
    central_sig = b"PK\x01\x02"
    eocd_sig = b"PK\x05\x06"

    with open(zip_path, "rb") as source:
        blob = bytearray(source.read())

    with zipfile.ZipFile(zip_path, "r") as archive:
        infos = archive.infolist()

    samsung_dos_date = 32

    for info in infos:
        offset = info.header_offset
        if blob[offset:offset + 4] != local_sig:
            continue

        flag_bits = entry_flags.get(info.filename)
        if flag_bits is None:
            method = struct.unpack_from("<H", blob, offset + 8)[0]
            flag_bits = 0x0800 if method == zipfile.ZIP_STORED else 0x0806

        struct.pack_into("<H", blob, offset + 6, flag_bits)
        struct.pack_into("<H", blob, offset + 10, 0)
        struct.pack_into("<H", blob, offset + 12, samsung_dos_date)

    eocd_offset = blob.rfind(eocd_sig)
    if eocd_offset >= 0:
        total_entries = struct.unpack_from("<H", blob, eocd_offset + 10)[0]
        central_offset = struct.unpack_from("<I", blob, eocd_offset + 16)[0]

        cursor = central_offset
        for _ in range(total_entries):
            if blob[cursor:cursor + 4] != central_sig:
                break

            struct.pack_into("<H", blob, cursor + 4, 0)

            file_name_length = struct.unpack_from("<H", blob, cursor + 28)[0]
            extra_length = struct.unpack_from("<H", blob, cursor + 30)[0]
            comment_length = struct.unpack_from("<H", blob, cursor + 32)[0]

            name_start = cursor + 46
            name_end = name_start + file_name_length
            name_bytes = bytes(blob[name_start:name_end])

            try:
                filename = name_bytes.decode("utf-8")
            except UnicodeDecodeError:
                filename = name_bytes.decode("cp437")

            flag_bits = entry_flags.get(filename)
            if flag_bits is None:
                method = struct.unpack_from("<H", blob, cursor + 10)[0]
                flag_bits = 0x0800 if method == zipfile.ZIP_STORED else 0x0806

            struct.pack_into("<H", blob, cursor + 8, flag_bits)
            struct.pack_into("<H", blob, cursor + 12, 0)
            struct.pack_into("<H", blob, cursor + 14, samsung_dos_date)
            struct.pack_into("<I", blob, cursor + 38, 0)

            cursor += 46 + file_name_length + extra_length + comment_length

    with open(zip_path, "wb") as target:
        target.write(blob)


def _append_end_tag_trailer(zip_path, end_tag_path):
    with open(end_tag_path, "rb") as source:
        trailer = source.read()

    with open(zip_path, "ab") as target:
        target.write(trailer)


def _zip_info_for(rel_path, compress_type):
    info = zipfile.ZipInfo(filename=rel_path, date_time=DOS_EPOCH)
    info.compress_type = compress_type
    info.create_system = 0
    info.external_attr = 0
    return info


def compress_to_sdocx(src_folder, dst_path):
    content_root = _detect_content_root(src_folder)
    file_map = {}

    for root, dirs, files in os.walk(content_root):
        for file in files:
            full_path = os.path.join(root, file)

            rel_path = os.path.relpath(full_path, content_root)
            rel_path = rel_path.replace("\\", "/")
            file_map[rel_path] = full_path

    _validate_required_members(file_map)
    ordered_paths = _build_ordered_entries(file_map)
    entry_flags = {}

    with zipfile.ZipFile(dst_path, "w", strict_timestamps=False) as z:
        for rel_path in ordered_paths:
            full_path = file_map[rel_path]
            compress_type = _compress_type_for(rel_path)
            entry_flags[rel_path] = _target_flag_for(rel_path, compress_type)
            zip_info = _zip_info_for(rel_path, compress_type)

            with open(full_path, "rb") as source:
                data = source.read()

            if compress_type == zipfile.ZIP_DEFLATED:
                z.writestr(zip_info, data, compress_type=compress_type, compresslevel=1)
            else:
                z.writestr(zip_info, data, compress_type=compress_type)

    _rewrite_zip_headers(dst_path, entry_flags)
    _append_end_tag_trailer(dst_path, file_map["end_tag.bin"])
