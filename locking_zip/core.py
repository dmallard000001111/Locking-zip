"""Zip + password-protect engine. No Tk here -- this module is fully unit-testable
without a display, and is imported by both the GUI worker thread and the tests.

Two encryption modes:
- "standard": legacy ZipCrypto (the classic PKWARE zip password scheme). Opens with
  a plain double-click + password prompt on stock Windows (Explorer) and macOS
  (Archive Utility) -- no extra software needed -- at the cost of being
  cryptographically weak (crackable with modern tools/known-plaintext attacks).
- "aes": real AES-256 (WinZip AES / WZ_AES). Much stronger, but neither OS's
  built-in unzip understands it, so opening the result needs a third-party tool
  (7-Zip on Windows, Keka/The Unarchiver on Mac).

pyzipper can only WRITE its AES format (AESZipFile) -- its plain ZipFile.get_encrypter()
is an unimplemented stub, so it can only READ legacy ZipCrypto, never write it. There's
no maintained pure-Python (or reliably-wheeled) library that writes legacy ZipCrypto
zips, so LegacyZipEncrypter below implements the classic PKWARE stream cipher directly
(mirroring the algorithm pyzipper's own CRCZipDecrypter already uses for reading) and
plugs into pyzipper's ZipFile via the same get_encrypter() extension point real AES
support uses. Everything else (compression, headers, zip64, directory bookkeeping) is
pyzipper's normal, well-tested code path -- only the cipher itself is new.

Reading (extract_zip) always goes through pyzipper.AESZipFile regardless of which
mode wrote the file -- verified empirically that it transparently handles legacy
ZipCrypto entries, AES entries, and unencrypted entries through one code path, so
there's no need to detect the mode before opening a zip to unlock it.
"""
import errno
import os
import shutil
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


MODE_STANDARD = "standard"
MODE_AES = "aes"


class EncryptionError(Exception):
    """Base class for all user-facing encryption/decryption failures."""


class OutputExistsError(EncryptionError):
    pass


class CancelledError(EncryptionError):
    pass


class DiskFullError(EncryptionError):
    pass


class PermissionDeniedError(EncryptionError):
    pass


class WrongPasswordError(EncryptionError):
    pass


class UnsafePathError(EncryptionError):
    pass


def _is_disk_full(exc: OSError) -> bool:
    if getattr(exc, "errno", None) == errno.ENOSPC:
        return True
    return getattr(exc, "winerror", None) == 112


def _open_writer(mode: str, tmp_path: Path) -> pyzipper.ZipFile:
    if mode == MODE_STANDARD:
        return _LegacyZipFile(tmp_path, "w", compression=pyzipper.ZIP_DEFLATED)
    if mode == MODE_AES:
        return pyzipper.AESZipFile(
            tmp_path,
            "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
            encryption_kwargs={"nbits": 256},
        )
    raise ValueError(f"Unknown encryption mode: {mode!r}")


def encrypt_to_zip(
    entries: List[Tuple[Path, str]],
    dest_zip: Path,
    password: str,
    *,
    mode: str = MODE_STANDARD,
    total_size: Optional[int] = None,
    overwrite: bool = False,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Write `entries` (as produced by fsutil.collect_entries) into dest_zip as a
    password-protected zip, using `mode` (MODE_STANDARD or MODE_AES).

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
        with _open_writer(mode, tmp_path) as zf:
            zf.setpassword(password.encode("utf-8"))
            zinfo_cls = zf.zipinfo_cls
            bytes_done = 0
            for abs_path, arcname in entries:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("Encryption cancelled")
                zinfo = zinfo_cls.from_file(abs_path, arcname)
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


def extract_zip(
    source_zip: Path,
    dest_dir: Path,
    password: str,
    *,
    progress_cb: Optional[ProgressCallback] = None,
    cancel_event: Optional[threading.Event] = None,
    chunk_size: int = 1024 * 1024,
) -> Path:
    """Extract every file in source_zip (legacy ZipCrypto, AES-256, or
    unencrypted -- auto-handled by pyzipper.AESZipFile regardless of which wrote
    it) into dest_dir.

    Extracts into a temporary sibling directory and renames it into place only
    on full success, so a cancelled/failed extraction never leaves a half-
    populated dest_dir. Every member's resolved path is validated to stay under
    dest_dir before anything is written (zip-slip protection) -- this has to be
    done explicitly since streaming per-entry for progress/cancel support means
    stdlib zipfile's own extractall() path-sanitizing never runs.

    Raises WrongPasswordError, UnsafePathError, CancelledError, DiskFullError,
    PermissionDeniedError, or EncryptionError. Never includes `password` in any
    exception message, log line, or filename.
    """
    source_zip = Path(source_zip)
    dest_dir = Path(dest_dir)
    tmp_dir = dest_dir.with_name(dest_dir.name + ".part")
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)

    try:
        with pyzipper.AESZipFile(source_zip) as zf:
            pwd_bytes = password.encode("utf-8")
            dest_root = tmp_dir.resolve()

            targets = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                target = (tmp_dir / info.filename).resolve()
                if dest_root not in target.parents:
                    raise UnsafePathError(f"Zip entry escapes destination: {info.filename}")
                targets.append((info, target))

            total_size = sum(info.file_size for info, _ in targets) or 1
            tmp_dir.mkdir(parents=True, exist_ok=True)

            bytes_done = 0
            for info, target in targets:
                if cancel_event is not None and cancel_event.is_set():
                    raise CancelledError("Extraction cancelled")
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, mode="r", pwd=pwd_bytes) as src, open(target, "wb") as dst:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise CancelledError("Extraction cancelled")
                        chunk = src.read(chunk_size)
                        if not chunk:
                            break
                        dst.write(chunk)
                        bytes_done += len(chunk)
                        if progress_cb is not None:
                            progress_cb(bytes_done, total_size, info.filename)
    except RuntimeError as e:
        _cleanup_dir(tmp_dir)
        if "bad password" in str(e).lower():
            raise WrongPasswordError("Incorrect password") from e
        raise EncryptionError(str(e)) from e
    except (CancelledError, UnsafePathError):
        _cleanup_dir(tmp_dir)
        raise
    except PermissionError as e:
        _cleanup_dir(tmp_dir)
        raise PermissionDeniedError(str(getattr(e, "filename", None) or e)) from e
    except OSError as e:
        _cleanup_dir(tmp_dir)
        if _is_disk_full(e):
            raise DiskFullError("Not enough disk space to finish") from e
        raise EncryptionError(str(e)) from e
    except Exception as e:
        _cleanup_dir(tmp_dir)
        raise EncryptionError(str(e)) from e

    if dest_dir.exists():
        shutil.rmtree(dest_dir)
    os.replace(tmp_dir, dest_dir)
    return dest_dir


def _cleanup(tmp_path: Path) -> None:
    try:
        tmp_path.unlink()
    except FileNotFoundError:
        pass


def _cleanup_dir(tmp_dir: Path) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)
