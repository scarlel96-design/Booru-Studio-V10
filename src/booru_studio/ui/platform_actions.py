from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class PlatformActionError(RuntimeError):
    pass


def _existing_file(path_text: str) -> Path:
    path = Path(path_text).expanduser()
    if not path.is_file():
        raise PlatformActionError("The downloaded file is no longer available at the recorded path.")
    return path


def open_file(path_text: str) -> None:
    path = _existing_file(path_text)
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return
    command = ["open", str(path)] if sys.platform == "darwin" else ["xdg-open", str(path)]
    try:
        subprocess.Popen(command, close_fds=True)
    except OSError as exc:
        raise PlatformActionError("The operating system could not open the downloaded file.") from exc


def reveal_file(path_text: str) -> None:
    path = _existing_file(path_text)
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", str(path)], close_fds=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", str(path.parent)], close_fds=True)
    except OSError as exc:
        raise PlatformActionError("The operating system could not reveal the downloaded file.") from exc
