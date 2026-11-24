"""File type validation: extension whitelist AND magic number.

The upload endpoint decides the format with a *double* check:
1. the file name extension must be in the whitelist (pdf/docx/jpg/png),
2. the first bytes of the file must match the magic number of that format.

When the two disagree the REAL type wins and the upload is rejected with
HTTP 415 - a renamed ``.exe`` or a PDF wearing a ``.png`` extension never
gets through.
"""

from __future__ import annotations

from dataclasses import dataclass

ALLOWED_EXTENSIONS: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "jpg": "image/jpeg",
    "png": "image/png",
}

MAGIC_NUMBERS: dict[str, tuple[bytes, ...]] = {
    "pdf": (b"%PDF-",),
    "jpg": (b"\xff\xd8\xff",),
    "png": (b"\x89PNG\r\n\x1a\n",),
}

DOCX_MARKER = b"[Content_Types].xml"
DOCX_ZIP_MAGIC = b"PK\x03\x04"

HEAD_BYTES = 4096


class UnsupportedMediaTypeError(Exception):
    """Raised when the file is not one of the allowed formats."""

    def __init__(self, message: str, *, expected: str | None = None, actual: str | None = None) -> None:
        super().__init__(message)
        self.expected = expected
        self.actual = actual


@dataclass(frozen=True)
class FileTypeDecision:
    ext: str
    content_type: str
    from_magic: bool


def normalize_extension(filename: str | None) -> str | None:
    """Return the lower-cased extension of ``filename`` (without the dot).

    Only the LAST path segment is considered, so ``../../x.pdf`` yields
    ``pdf`` and never influences the stored object key.
    """
    if not filename:
        return None
    base = str(filename).replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in base:
        return None
    ext = base.rsplit(".", 1)[-1].strip().lower()
    return ext or None


def detect_content_type(head: bytes) -> str | None:
    """Detect the REAL format from the magic number of ``head``."""
    if not head:
        return None
    for ext, magics in MAGIC_NUMBERS.items():
        for magic in magics:
            if head.startswith(magic):
                return ALLOWED_EXTENSIONS[ext]
    if head.startswith(DOCX_ZIP_MAGIC):
        if DOCX_MARKER in head:
            return ALLOWED_EXTENSIONS["docx"]
        return None
    return None


def extension_for_content_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    for ext, mime in ALLOWED_EXTENSIONS.items():
        if mime == content_type:
            return ext
    return None


def resolve_extension(filename: str | None, head: bytes) -> FileTypeDecision:
    """Double check the extension against the magic number.

    Raises :class:`UnsupportedMediaTypeError` when
    * the extension is not whitelisted, or
    * the magic number says something else than the extension.
    """
    ext = normalize_extension(filename)
    actual_content_type = detect_content_type(head)
    actual_ext = extension_for_content_type(actual_content_type)

    if ext is None or ext not in ALLOWED_EXTENSIONS:
        raise UnsupportedMediaTypeError(
            f"file extension {ext!r} is not allowed; allowed: {sorted(ALLOWED_EXTENSIONS)}",
            expected=None,
            actual=actual_ext,
        )
    if actual_ext is None:
        raise UnsupportedMediaTypeError(
            "file content does not match any allowed format "
            f"(magic number check failed for extension {ext!r})",
            expected=ext,
            actual=None,
        )
    if actual_ext != ext:
        raise UnsupportedMediaTypeError(
            f"file content is {actual_ext!r} but the file name claims {ext!r}; "
            "the real type wins and the upload is rejected",
            expected=ext,
            actual=actual_ext,
        )
    return FileTypeDecision(
        ext=ext,
        content_type=ALLOWED_EXTENSIONS[ext],
        from_magic=True,
    )
