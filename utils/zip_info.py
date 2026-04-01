import zipfile
METHOD_NAMES = {
    zipfile.ZIP_STORED: "STORED",
    zipfile.ZIP_DEFLATED: "DEFLATED",
    zipfile.ZIP_BZIP2: "BZIP2",
    zipfile.ZIP_LZMA: "LZMA",
}

def get_zip_info(file_dir):
    try:
        with zipfile.ZipFile(file_dir) as z:
            for index, info in enumerate(z.infolist(), start=1):
                method_name = METHOD_NAMES.get(info.compress_type, str(info.compress_type))
                timestamp = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(*info.date_time)
                print(
                    f"#{index}",
                    info.filename,
                    "time=", timestamp,
                    "size=", info.file_size,
                    "compressed=", info.compress_size,
                    "method=", method_name,
                )
    except Exception as e:
        print(f"Something went wrong when opening {file_dir}: {e}")
