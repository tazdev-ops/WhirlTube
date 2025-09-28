from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue

PREFIX = "WTJSON:"  # marker for JSON lines we emit

PRINT_HOOKS = [
    "--print",
    f'{PREFIX}{{"type": "pre_download"}}',
    "--print",
    f'{PREFIX}{{"type": "end_of_playlist"}}',
    "--print",
    f'{PREFIX}{{"type": "end_of_video"}}',
]

PROGRESS_TPL = [
    "--progress-template",
    f'{PREFIX}{{"type":"downloading","eta":%(progress.eta)s,'
    f'"downloaded_bytes":%(progress.downloaded_bytes)s,'
    f'"total_bytes":%(progress.total_bytes)s,'
    f'"total_bytes_estimate":%(progress.total_bytes_estimate)s,'
    f'"elapsed":%(progress.elapsed)s,"speed":%(progress.speed)s,'
    f'"playlist_count":%(info.playlist_count)s,'
    f'"playlist_index":%(info.playlist_index)s}}',
]


@dataclass
class ProgressEvent:
    kind: str
    payload: dict

def parse_line(line: str) -> list[ProgressEvent] | Exception | None:
    if line.startswith("stderr:ERROR: "):
        return RuntimeError(line[len("stderr:ERROR: ") :].strip())
    if line.startswith("ERROR: "):
        return RuntimeError(line[len("ERROR: ") :].strip())
    if line.startswith("stderr:") and PREFIX not in line:
        return RuntimeError(f"yt-dlp error: {line[8:].strip()}")
    idx = line.find(PREFIX)
    if idx < 0:
        return None
    part = line[idx + len(PREFIX) :].strip()
    try:
        obj = json.loads(part.replace("NA", "null"))
        if isinstance(obj, dict) and "type" in obj:
            return [ProgressEvent(obj["type"], obj)]
    except Exception:
        return None
    return None

class YtDlpRunner:
    def __init__(self, on_progress: Callable[[str], None]):
        self._on_progress = on_progress
        self._proc: subprocess.Popen | None = None
        self._q: Queue[str] = Queue()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, args: list[str], bin_path: str | None = None) -> bool:
        self.stop()
        cmd = [bin_path or "yt-dlp"] + args + PRINT_HOOKS + PROGRESS_TPL + ["--no-quiet"]
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        threading.Thread(target=self._pump, daemon=True).start()
        return True

    def stop(self) -> None:
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
            try:
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _pump(self) -> None:
        assert self._proc and self._proc.stdout and self._proc.stderr

        def reader(stream, prefix: str):
            while True:
                chunk = stream.readline()
                if not chunk:
                    break
                try:
                    text = chunk.decode(errors="ignore")
                except Exception:
                    continue
                self._q.put(prefix + text)

        t1 = threading.Thread(target=reader, args=(self._proc.stdout, ""), daemon=True)
        t2 = threading.Thread(target=reader, args=(self._proc.stderr, "stderr:"), daemon=True)
        t1.start()
        t2.start()

        while self._proc:
            try:
                line = self._q.get(timeout=0.2)
            except Empty:
                continue
            self._on_progress(line)

        while not self._q.empty():
            try:
                line = self._q.get_nowait()
            except Empty:
                break
            self._on_progress(line)
