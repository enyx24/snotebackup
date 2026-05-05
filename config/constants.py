import zipfile

METHOD_NAMES = {
    zipfile.ZIP_STORED: "STORED",
    zipfile.ZIP_DEFLATED: "DEFLATED",
    zipfile.ZIP_BZIP2: "BZIP2",
    zipfile.ZIP_LZMA: "LZMA",
}

DOS_EPOCH = (1980, 1, 1, 0, 0, 0)

_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

MARKER_FILES = {"note.note", "end_tag.bin", "pageIdInfo.dat"}