"""Zip + password-protect engine. No Tk here -- this module is fully unit-testable
without a display, and is imported by both the GUI worker thread and the tests.

Encryption is legacy ZipCrypto (the classic PKWARE zip password scheme), not AES.
This is a deliberate choice: AES-encrypted zips can't be opened with a plain
double-click on stock Windows (Explorer's "Extract All") or stock macOS (Archive
Utility) -- both only understand ZipCrypto, so AES would require every recipient to
install a third-party tool (7-Zip, Keka) anyway. ZipCrypto opens natively everywhere
with just a password prompt, at the cost of being cryptographically weak (crackable
with modern tools/known-plaintext attacks) -- acceptable here since the goal is
casual protection with zero-friction compatibility, not high-security encryption.

pyzipper can only WRITE its AES format (AESZipFile) -- its plain ZipFile.get_encrypter()
is an unimplemented stub, so it can only READ legacy ZipCrypto, never write it. There's
no maintained pure-Python (or reliably-wheeled) library that writes legacy ZipCrypto
zips, so LegacyZipEncrypter below implements the classic PKWARE stream cipher directly
(mirroring the algorithm pyzipper's own CRCZipDecrypter already uses for reading) and
plugs into pyzipper's ZipFile via the same get_encrypter() extension point real AES
support uses. Everything else (compression, headers, zip64, directory bookkeeping) is
pyzipper's normal, well-tested code path -- only the cipher itself is new.
"""
import errno
import os
import threading
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import pyzipper

ProgressCallback = Callable[[int, int, str], None]  # (bytes_done, bytes_total, current_name)

# General-purpose bit flag 3 ("data descriptor follows"), per the PKZIP APPNOTE.
# Forcing this on lets us pick the encryption header's password-check byte from the
# file's DOS mod-time (known upfront) instead of its CRC32 (only known after streaming
# the whole file), so encryption stays single-pass even for large files.
_FLAG_DATA_DESCRIPTOR = 0x08

_CRC_TABLE = None


def _crc_table():
    global _CRC_TABLE
    if _CRC_TABLE is None:
        table = []
        for i in range(256):
            crc = i
            for _ in range(8):
                crc = (crc >> 1) ^ 0xEDB88320 if crc & 1 else crc >> 1
            table.append(crc)
        _CRC_TABLE = table
    return _CRC_TABLE


class LegacyZipEncrypter:
    """Classic PKWARE/ZipCrypto stream cipher, matching pyzipper's read-side
    CRCZipDecrypter exactly (same 3-key mixing, same keystream-byte derivation) so
    that any legacy-zip reader -- pyzipper itself, 7-Zip, Explorer, Archive
    Utility -- can decrypt what this writes."""

    def __init__(self, pwd: bytes):
        self._table = _crc_table()
        self.key0 = 305419896
        self.key1 = 591751049
        self.key2 = 878082192
        for c in pwd:
            self._update_keys(c)
        self._check_byte = 0

    def _crc32(self, ch: int, crc: int) -> int:
        return (crc >> 8) ^ self._table[(crc ^ ch) & 0xFF]

    def _update_keys(self, plain_byte: int) -> None:
        self.key0 = self._crc32(plain_byte, self.key0)
        self.key1 = (self.key1 + (self.key0 & 0xFF)) & 0xFFFFFFFF
        self.key1 = (self.key1 * 134775813 + 1) & 0xFFFFFFFF
        self.key2 = self._crc32(self.key1 >> 24, self.key2)

    def _encrypt_bytes(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        for i, plain_byte in enumerate(data):
            k = self.key2 | 2
            out[i] = plain_byte ^ (((k * (k ^ 1)) >> 8) & 0xFF)
            self._update_keys(plain_byte)
        return bytes(out)

    def update_zipinfo(self, zipinfo) -> None:
        zipinfo.flag_bits |= _FLAG_DATA_DESCRIPTOR
        self._check_byte = (zipinfo.get_dostime() >> 8) & 0xFF

    def finalize_zipinfo(self, zipinfo) -> None:
        pass

    def encryption_header(self) -> bytes:
        header = bytearray(os.urandom(11))
        header.append(self._check_byte)
        return self._encrypt_bytes(bytes(header))

    def encrypt(self, data: bytes) -> bytes:
        return self._encrypt_bytes(data)

    def flush(self) -> bytes:
        return b""


class _LegacyZipFile(pyzipper.ZipFile):
    def get_encrypter(self):
        return LegacyZipEncrypter(self.pwd)


class EncryptionError(Exception):
    """Base class for all user-facing encryption failures."""


class OutputExistsError(EncryptionError):
    pass


class CancelledError(EncryptionError):
    pass


class DiskFullError(EncryptionError):
    pass


class PermissionDeniedError(EncryptionError):
    pass


def _is_disk_full(exc: OSError) -> bool:
    if getattr(exc, "errno", None) == errno.ENOSPC:
        return True
    return getattr(exc, "winerror", None) == 112


def encrypt_to_zip(
    entries: List[Tuple[Path, str]],
    dest_zip: Path,
    password: str,
    *,
    total_size: Optional[int] = None,
    overwrite: bool = False,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Write `entries` (as produced by fsutil.collect_entries) into dest_zip as a
    legacy-ZipCrypto password-protected zip.

    Writes to a temporary `dest_zip.part` file in the same directory and only
    os.replace()s it onto dest_zip on full success, so a crash, cancellation, or
    error never leaves a partial/corrupt file at the destination name.

    Raises OutputExistsError, CancelledError, DiskFullError,
    PermissionDeniedError, or EncryptionError. Never includes `password` in any
    exception message, log line, or filename.
    """
    dest_zip = Path(dest_zip)
    if dest_zip.exists() and not overwrite:
        raise OutputExistsError(f"{dest_zip} already exists")

    if total_size is None:
        total_size = sum(abs_path.stat().st_size for abs_path, _ in entries)

    tmp_path = dest_zip.with_name(dest_zip.name + ".part")

    try:
        with _LegacyZipFile(tmp_path, "w", compression=pyzipper.ZIP_DEFLATED) as zf:
            zf.setpassword(password.encode("utf-8"))
            bytes_done = 0
            for abs_path, arcname in entries:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("Encryption cancelled")
                zinfo = pyzipper.ZipInfo.from_file(abs_path, arcname)
                zinfo.compress_type = pyzipper.ZIP_DEFLATED
                with open(abs_path, "rb") as src, zf.open(zinfo, mode="w") as dst:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise CancelledError("Encryption cancelled")
                        chunk = src.read(chunk_size)
                        if not chunk:
                            break
                        dst.write(chunk)
                        bytes_done += len(chunk)
                        if progress_cb is not None:
                            progress_cb(bytes_done, total_size, arcname)
    except CancelledError:
        _cleanup(tmp_path)
        raise
    except PermissionError as e:
        _cleanup(tmp_path)
        raise PermissionDeniedError(str(getattr(e, "filename", None) or e)) from e
    except OSError as e:
        _cleanup(tmp_path)
        if _is_disk_full(e):
            raise DiskFullError("Not enough disk space to finish") from e
        raise EncryptionError(str(e)) from e
    except Exception as e:
        _cleanup(tmp_path)
        raise EncryptionError(str(e)) from e

    os.replace(tmp_path, dest_zip)
    return dest_zip


def _cleanup(tmp_path: Path) -> None:
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass
