from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from queue import Empty, Queue
from shlex import quote as shlex_quote
import logging

log = logging.getLogger(__name__)

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
    """Parse a line from yt-dlp output. Returns events, error, or None."""
    
    # Only treat explicit ERROR lines as errors
    if line.startswith("stderr:ERROR: "):
        return RuntimeError(line[len("stderr:ERROR: ") :].strip())
    if line.startswith("ERROR: "):
        return RuntimeError(line[len("ERROR: ") :].strip())
    
    # ✅ CRITICAL FIX: Ignore non-prefixed stderr lines (they're normal yt-dlp chatter)
    # Before this fix, ANY stderr line would abort the download
    if line.startswith("stderr:") and PREFIX not in line:
        log.debug(f"Ignoring stderr: {line[8:60]}...")  # Log first 60 chars for debugging
        return None
    
    # Parse JSON-prefixed progress events
    idx = line.find(PREFIX)
    if idx < 0:
        return None
    
    part = line[idx + len(PREFIX) :].strip()
    try:
        obj = json.loads(part.replace("NA", "null"))
        if isinstance(obj, dict) and "type" in obj:
            log.debug(f"Progress event: {obj['type']}")  # Debug logging
            return [ProgressEvent(obj["type"], obj)]
    except Exception as e:
        log.debug(f"Failed to parse JSON: {e}")
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
        log.debug("Starting yt-dlp: %s", " ".join(shlex_quote(x) for x in cmd))
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
                log.debug(f"yt-dlp output ({prefix}): {text[:100]}")  # ✅ NEW: Log raw output
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
            log.debug(f"Processing line: {line[:100]}")  # ✅ NEW: Log what we're processing
            self._on_progress(line)

        while not self._q.empty():
            try:
                line = self._q.get_nowait()
            except Empty:
                break
            self._on_progress(line)
