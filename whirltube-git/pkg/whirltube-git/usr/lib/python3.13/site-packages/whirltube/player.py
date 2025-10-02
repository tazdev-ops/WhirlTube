from __future__ import annotations

import json
import os
import shlex
import shutil
import socket
import subprocess
from collections.abc import Sequence

_OPTION_CACHE: dict[str, bool] = {}

def mpv_supports_option(opt: str) -> bool:
    # Detect supported options once via --list-options (mpv ≥ 0.30)
    if opt in _OPTION_CACHE:
        return _OPTION_CACHE[opt]
    ok = False
    try:
        res = subprocess.run(
            ["mpv", "--no-config", "--list-options"],
            capture_output=True, text=True, timeout=2,
        )
        if res.returncode == 0:
            names = set()
            for line in res.stdout.splitlines():
                if not line:
                    continue
                head = line.split()[0]
                names.add(head.split("=")[0])
            opts = names
            ok = opt in opts
        else:
            ok = False
    except Exception:
        ok = False
    _OPTION_CACHE[opt] = ok
    return ok


def has_mpv() -> bool:
    return shutil.which("mpv") is not None


def start_mpv(
    url: str,
    extra_args: str | Sequence[str] | None = None,
    ipc_server_path: str | None = None,
    extra_env: dict[str, str] | None = None,
    log_file_path: str | None = None,
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
    if log_file_path:
        args += ["--msg-level=all=v", f"--log-file={log_file_path}"]
    if isinstance(extra_args, str) and extra_args.strip():
        args.extend(shlex.split(extra_args))
    elif isinstance(extra_args, (list, tuple)):
        args.extend(extra_args)
    args.append(url)

    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    return subprocess.Popen(args, env=env)


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
