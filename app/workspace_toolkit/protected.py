"""Password-protected Office files: opened with the person's password, in memory.

A Word, PowerPoint or Excel file can be locked with a password. Google cannot
open one, and neither can the readers here, so it is unlocked first. This runs
inside the analysis worker, beside the parsers, because it reads untrusted
bytes: the password reaches it on standard input, never on the command line or
in the environment, and is used once, here. It is never written down, put in a
report or logged, and the unlocked copy lives only in the job's own folder,
which is deleted when the job ends.
"""

from __future__ import annotations

import io
from pathlib import Path

import msoffcrypto  # type: ignore[import-untyped, unused-ignore]
from msoffcrypto.exceptions import InvalidKeyError  # type: ignore[import-untyped, unused-ignore]

from .config import Settings
from .errors import ToolkitError

# An OLE compound file: what a legacy .doc is, and what wraps a protected
# .docx, .pptx or .xlsx (whose real package sits inside, encrypted).
CFB_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

UNSUPPORTED = ToolkitError(
    "protection_unsupported",
    "This file's password protection could not be removed here.",
    422,
)


def is_compound(path: Path) -> bool:
    with path.open("rb") as stream:
        return stream.read(8) == CFB_SIGNATURE


def unlock(source: Path, password: str | None, settings: Settings | None = None) -> bool:
    """Replaces a protected file with its unlocked copy. False if it was not protected.

    Raises `password_required` when it is protected and no password was given,
    and `wrong_password` when the password does not open it.
    """
    settings = settings or Settings()
    if not is_compound(source):
        return False
    try:
        with source.open("rb") as stream:
            office = msoffcrypto.OfficeFile(stream)
            if not office.is_encrypted():
                return False
            if not password:
                raise ToolkitError(
                    "password_required",
                    "This file is password protected. Enter its password and try again.",
                    422,
                )
            try:
                office.load_key(password=password)
                unlocked = io.BytesIO()
                office.decrypt(unlocked)
            except InvalidKeyError:
                raise ToolkitError(
                    "wrong_password",
                    "That password did not open the file. Check it and try again.",
                    422,
                ) from None
    except ToolkitError:
        raise
    except Exception:  # noqa: BLE001  # an unreadable or unsupported protection
        raise ToolkitError(UNSUPPORTED.code, UNSUPPORTED.message, UNSUPPORTED.status) from None
    data = unlocked.getvalue()
    if not data or len(data) > settings.max_expanded_bytes:
        raise ToolkitError(UNSUPPORTED.code, UNSUPPORTED.message, UNSUPPORTED.status)
    source.write_bytes(data)
    return True
