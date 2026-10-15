"""Hardened ZIP intake. Standard library only. The archive is never extracted to disk and nothing in it is executed.

Everything the client says (filename, MIME type, declared sizes) is untrusted: content is checked, sizes are
counted while streaming, and anything unsafe rejects the whole upload. Files that are merely unsupported are
NOT dropped silently; each appears in the inventory with a status and a reason.
"""
import hashlib
import io
import re
import stat
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import PurePosixPath


class IntakeError(ValueError):
    """The archive is unsafe or unusable. The message is safe to show to the uploader."""


@dataclass(frozen=True)
class Limits:
    max_archive_bytes: int = 50_000_000
    max_entries: int = 300
    max_file_bytes: int = 50_000_000
    max_total_bytes: int = 200_000_000
    max_ratio: int = 100          # uncompressed / compressed, applied to entries above ratio_floor_bytes
    ratio_floor_bytes: int = 1_000_000
    max_path_len: int = 255
    max_depth: int = 8


SUPPORTED_EXT = {".pdf"}
IGNORED_NAMES = {".ds_store", "thumbs.db", "desktop.ini"}
_DRIVE = re.compile(r"^[A-Za-z]:")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


def normalize_name(raw):
    if _CONTROL.search(raw):
        raise IntakeError("archive member name contains control characters")
    name = raw.replace("\\", "/")
    if name.startswith("/") or _DRIVE.match(name):
        raise IntakeError("archive member has an absolute path")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise IntakeError("archive member escapes the archive root")
    return "/".join(parts)


def _read_limited(zf, info, remaining_total, limits):
    cap = min(limits.max_file_bytes, remaining_total)
    buf = io.BytesIO()
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(65536)
                if not chunk:
                    break
                buf.write(chunk)
                if buf.tell() > cap:
                    raise IntakeError("archive member expands beyond the allowed size")
    except (zipfile.BadZipFile, zlib.error, EOFError, RuntimeError, NotImplementedError, OSError):
        raise IntakeError("archive member is corrupt or inconsistent")
    data = buf.getvalue()
    if len(data) != info.file_size:
        raise IntakeError("archive member size does not match its header")
    return data


def inventory(data, limits=Limits()):
    """Validate the archive and return {'archive_sha256', 'entries': [...], 'documents': [(name, bytes)]}.

    entries[*].status is one of: accepted, skipped_unsupported, skipped_ignored.
    Raises IntakeError for anything unsafe, and when no supported document is present.
    """
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise IntakeError("empty upload")
    if len(data) > limits.max_archive_bytes:
        raise IntakeError("archive is too large")
    if not bytes(data[:4]) in _ZIP_MAGICS:
        raise IntakeError("upload is not a ZIP archive")
    try:
        zf = zipfile.ZipFile(io.BytesIO(bytes(data)))
    except zipfile.BadZipFile:
        raise IntakeError("upload is not a valid ZIP archive")
    infos = zf.infolist()
    if len(infos) > limits.max_entries:
        raise IntakeError("archive has too many entries")

    entries, documents, seen = [], [], set()
    declared_total = actual_total = 0
    for info in infos:
        if info.is_dir():
            normalize_name(info.filename)  # still must not escape
            continue
        name = normalize_name(info.filename)
        if len(name) > limits.max_path_len or len(name.split("/")) > limits.max_depth:
            raise IntakeError("archive member path is too long or too deep")
        key = name.casefold()
        if key in seen:
            raise IntakeError("archive contains duplicate member names")
        seen.add(key)
        file_type = stat.S_IFMT(info.external_attr >> 16)  # 0 when the creator recorded permissions only
        if file_type not in (0, stat.S_IFREG):
            raise IntakeError("archive contains a link or special file")
        if info.flag_bits & 0x1:
            raise IntakeError("archive contains an encrypted member")
        if info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise IntakeError("archive uses an unsupported compression method")
        if info.file_size > limits.max_file_bytes:
            raise IntakeError("archive member is too large")
        declared_total += info.file_size
        if declared_total > limits.max_total_bytes:
            raise IntakeError("archive expands beyond the allowed total size")
        if info.file_size > limits.ratio_floor_bytes and info.file_size > limits.max_ratio * max(info.compress_size, 1):
            raise IntakeError("archive member has a suspicious compression ratio")

        base = PurePosixPath(name).name.casefold()
        ext = PurePosixPath(name).suffix.casefold()
        if name.startswith("__MACOSX/") or base in IGNORED_NAMES:
            entries.append({"filename": name, "status": "skipped_ignored", "reason": "operating-system metadata"})
            continue
        raw = _read_limited(zf, info, limits.max_total_bytes - actual_total, limits)
        actual_total += len(raw)
        if raw[:4] in _ZIP_MAGICS:
            raise IntakeError("nested archives are not accepted")
        digest = hashlib.sha256(raw).hexdigest()
        if ext not in SUPPORTED_EXT:
            entries.append({"filename": name, "status": "skipped_unsupported", "sha256": digest, "bytes": len(raw),
                            "reason": f"unsupported file type {ext or '(none)'}"})
            continue
        if b"%PDF-" not in raw[:1024]:
            raise IntakeError("a file named .pdf is not a PDF")
        entries.append({"filename": name, "status": "accepted", "sha256": digest, "bytes": len(raw)})
        documents.append((name, raw))
    if not documents:
        raise IntakeError("archive contains no supported documents")
    return {"archive_sha256": hashlib.sha256(bytes(data)).hexdigest(), "entries": entries, "documents": documents}
