from __future__ import annotations

import json
import shlex
import shutil
import socket
import subprocess
from collections.abc import Sequence


def has_mpv() -> bool:
    return shutil.which("mpv") is not None


def start_mpv(
    url: str,
    extra_args: str | Sequence[str] | None = None,
    ipc_server_path: str | None = None,
) -> subprocess.Popen:
    """
    Launch MPV externally to play a URL. Optionally create a JSON IPC server at ipc_server_path.
    Returns the Popen handle.
    """
    if not has_mpv():
        raise RuntimeError("MPV is not installed or not found in PATH.")
    args = ["mpv", "--force-window=yes"]
    if ipc_server_path:
        args += [f"--input-ipc-server={ipc_server_path}"]
    if isinstance(extra_args, str) and extra_args.strip():
        args.extend(shlex.split(extra_args))
    elif isinstance(extra_args, (list, tuple)):
        args.extend(extra_args)
    args.append(url)
    return subprocess.Popen(args)


def play_in_mpv(url: str, extra_args: str | Sequence[str] | None = None) -> subprocess.Popen:
    """
    Backward-compatible helper without IPC. Prefer start_mpv() in new code.
    """
    return start_mpv(url, extra_args=extra_args, ipc_server_path=None)


def mpv_send_cmd(ipc_path: str, command: list) -> dict | None:
    """
    Send a JSON IPC command to MPV and return the parsed response, or None on failure.

    Example command lists:
      ["cycle", "pause"]
      ["seek", 10, "relative"]
      ["set_property", "speed", 1.25]
      ["quit"]
    """
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(ipc_path)
            payload = json.dumps({"command": command}) + "\n"
            s.sendall(payload.encode("utf-8", "ignore"))
            # Attempt to read a reply line (best effort)
            try:
                data = s.recv(4096)
                if data:
                    return json.loads(data.decode("utf-8", "ignore"))
            except Exception:
                return None
    except Exception:
        return None
    return None
