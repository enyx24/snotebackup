from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

@dataclass(frozen=True)
class NoteDB:
    Id: str
    UUID: str
    Title: str
    DeletedStatus: int
    CreatedAt: int
    LastModifiedAt: int
    FilePath: str
    CoverThumbnailPathRect: str 
    AccountName: str

class TextSearchDB:
    Id: str
    UUID: str
    StrippedContent: str
    PDFTextContents: str
    FilePath: str
    HWTextContent: Optional[str] = None

class DocumentCover:
    Id: str
    documentUUID: str
    templateUUID: str
    title: str
    createdAt: int
    lastModifiedAt: int