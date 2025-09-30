from __future__ import annotations

import logging
import os
import tempfile
import shlex
import secrets
import subprocess
import threading
from pathlib import Path

from ..models import Video
from ..mpv_embed import MpvWidget
from ..player import has_mpv, start_mpv, mpv_send_cmd
from ..app import APP_ID
from ..util import safe_httpx_proxy

import gi
from gi.repository import Gio, GLib, Gdk

log = logging.getLogger(__name__)


class PlaybackService:
    def __init__(self, mpv_widget: MpvWidget):
        self.mpv_widget = mpv_widget
        # External MPV state
        self._proc: subprocess.Popen | None = None
        self._ipc: str | None = None
        self._current_url: str | None = None
        self._speed = 1.0
        # Callbacks for UI updates
        self._on_started_callback = None
        self._on_stopped_callback = None

    def set_callbacks(self, on_started=None, on_stopped=None):
        """Set callbacks for playback events"""
        self._on_started_callback = on_started
        self._on_stopped_callback = on_stopped

    def play(
        self, 
        video: Video, 
        playback_mode: str, 
        mpv_args: str,
        quality: str | None,
        cookies_enabled: bool,
        cookies_browser: str,
        cookies_keyring: str,
        cookies_profile: str,
        cookies_container: str,
        http_proxy: str | None,
        fullscreen: bool = False,
        sb_enabled: bool = False,
        sb_mode: str = "mark",         # "mark" | "skip"
        sb_categories: str = "default",
    ) -> bool:
        # Detect Wayland/X11
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        is_wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

        # Quality preset -> ytdl-format
        ytdl_fmt_val = None
        if quality and quality != "auto":
            try:
                h = int(quality)
                ytdl_fmt_val = f'bv*[height<={h}]+ba/b[height<={h}]'
            except Exception:
                pass

        # Build base mpv args
        mpv_args_list = []
        if mpv_args:
            try:
                mpv_args_list = shlex.split(mpv_args)
            except Exception:
                log.warning("Failed to parse MPV args; launching without user args")

        if ytdl_fmt_val:
            mpv_args_list.append(f'--ytdl-format={ytdl_fmt_val}')

        # Build ytdl-raw-options map (cookies + sponsorblock + optional proxy)
        ytdl_raw: dict[str, str] = {}

        if cookies_enabled:
            val = self._cookie_spec(cookies_browser, cookies_keyring, cookies_profile, cookies_container)
            if val:
                ytdl_raw["cookies-from-browser"] = val

        # SponsorBlock for playback: mark chapters or auto-skip if script is present
        sb_mode_l = (sb_mode or "mark").strip().lower()
        if sb_enabled:
            cats = (sb_categories or "default").strip()
            # Escape commas for mpv CLI in case they appear (e.g., "all,-preview")
            cats_cli = cats.replace(",", r"\,")
            if sb_mode_l == "mark":
                ytdl_raw["sponsorblock-mark"] = cats_cli
            elif sb_mode_l in ("skip", "autoskip"):
                # Best effort: still mark chapters for visibility
                ytdl_raw["sponsorblock-mark"] = cats_cli
                # And try to load sponsorblock.lua to auto-skip
                sb_script = self._find_sponsorblock_script()
                if sb_script:
                    mpv_args_list.append(f"--script={sb_script}")
                else:
                    log.debug("SponsorBlock autoskip requested, but sponsorblock.lua not found; chapters will be marked only")

        # Fullscreen
        if fullscreen:
            mpv_args_list.append("--fs")

        # Add platform-specific args
        from ..player import mpv_supports_option
        extra_platform_args = []
        if is_wayland and mpv_supports_option("wayland-app-id"):
            extra_platform_args.append(f"--wayland-app-id={APP_ID}")
        if not is_wayland and mpv_supports_option("class"):
            extra_platform_args.append(f"--class={APP_ID}")
        final_mpv_args_list = mpv_args_list + extra_platform_args

        # Embedded path
        if playback_mode == "embedded":
            log.debug("Attempting embedded playback")
            try:
                self.mpv_widget.set_ytdl_format(ytdl_fmt_val)
            except Exception:
                pass
            # Pass ytdl-raw-options dict directly
            try:
                # Add proxy to raw opts for embedded too
                raw_opts = dict(ytdl_raw)
                if http_proxy:
                    raw_opts["proxy"] = http_proxy
                self.mpv_widget.set_ytdl_raw_options(raw_opts)
            except Exception:
                pass
            ok = self.mpv_widget.play(video.url)
            if ok:
                log.debug("Embedded playback started successfully")
                if self._on_started_callback:
                    self._on_started_callback("embedded")
                return True
            else:
                log.debug("Embedded playback failed, falling back to external")
        else:
            log.debug("Using external playback mode")

        # External MPV
        if not has_mpv():
            log.error("MPV not found in PATH")
            return False

        # Proxy env for mpv/ytdl
        extra_env = {}
        if http_proxy:
            extra_env["http_proxy"] = http_proxy
            extra_env["https_proxy"] = http_proxy

        # Unique IPC + optional log
        rnd = secrets.token_hex(4)
        ipc_dir = Path(tempfile.gettempdir())
        ipc_path = str(ipc_dir / f"whirltube-mpv-{os.getpid()}-{rnd}.sock")
        log_file = str(ipc_dir / f"whirltube-mpv-{os.getpid()}-{rnd}.log") if os.environ.get("WHIRLTUBE_DEBUG") else None

        # Append combined ytdl-raw-options CLI (single arg) if any
        ytdl_raw_cli = self._format_ytdl_raw_cli(ytdl_raw)
        if ytdl_raw_cli:
            final_mpv_args_list.append(f"--ytdl-raw-options={ytdl_raw_cli}")

        log.debug("Launching mpv: args=%s proxy=%s", final_mpv_args_list, bool(http_proxy))
        try:
            proc = start_mpv(
                video.url,
                extra_args=final_mpv_args_list,
                ipc_server_path=ipc_path,
                extra_env=extra_env,
                log_file_path=log_file,
            )
            self._proc = proc
            self._ipc = ipc_path
            self._current_url = video.url
            self._speed = 1.0
            if self._on_started_callback:
                self._on_started_callback("external")
            def _watch():
                try:
                    proc.wait()
                except Exception:
                    pass
                GLib.idle_add(self._on_external_mpv_exit)
            threading.Thread(target=_watch, daemon=True).start()
            return True
        except Exception as e:
            log.error("Failed to start mpv: %s", e)
            if os.environ.get("WHIRLTUBE_DEBUG") and log_file:
                log.error(f"Failed to start mpv. See log: {log_file}")
            else:
                log.error("Failed to start mpv. See logs for details.")
            return False

    # --- helpers ---

    def _cookie_spec(self, browser: str, keyring: str, profile: str, container: str) -> str:
        if not browser:
            return ""
        val = browser
        if keyring:
            val += f"+{keyring}"
        if profile or container:
            val += f":{profile}"
        if container:
            val += f"::{container}"
        return val

    def _find_sponsorblock_script(self) -> str | None:
        # Try common system/user locations
        candidates = [
            os.path.expanduser("~/.config/mpv/scripts/sponsorblock.lua"),
            "/usr/share/mpv/scripts/sponsorblock.lua",
            "/usr/local/share/mpv/scripts/sponsorblock.lua",
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    def _format_ytdl_raw_cli(self, opts: dict[str, str]) -> str:
        """
        Build a single --ytdl-raw-options value like:
          cookies-from-browser=firefox,sponsorblock-mark=default
        Values with commas are escaped as '\,' for mpv's parser.
        """
        parts = []
        for k, v in opts.items():
            if v is None:
                continue
            v = str(v)
            if "," in v:
                v = v.replace(",", r"\,")
            parts.append(f"{k}={v}")
        return ",".join(parts)

    def _cookie_spec(self, browser: str, keyring: str, profile: str, container: str) -> str:
        if not browser:
            return ""
        val = browser
        if keyring:
            val += f"+{keyring}"
        if profile or container:
            val += f":{profile}"
        if container:
            val += f"::{container}"
        return val

    def _find_sponsorblock_script(self) -> str | None:
        # Try common system/user locations
        candidates = [
            os.path.expanduser("~/.config/mpv/scripts/sponsorblock.lua"),
            "/usr/share/mpv/scripts/sponsorblock.lua",
            "/usr/local/share/mpv/scripts/sponsorblock.lua",
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return None

    def _format_ytdl_raw_cli(self, opts: dict[str, str]) -> str:
        """
        Build a single --ytdl-raw-options value like:
          cookies-from-browser=firefox,sponsorblock-mark=default
        Values with commas are escaped as '\,' for mpv's parser.
        """
        parts = []
        for k, v in opts.items():
            if v is None:
                continue
            v = str(v)
            if "," in v:
                v = v.replace(",", r"\,")
            parts.append(f"{k}={v}")
        return ",".join(parts)

    def _on_external_mpv_exit(self) -> None:
        """Called when external MPV process exits"""
        # Clean up the IPC socket file
        try:
            if self._ipc and os.path.exists(self._ipc):
                os.remove(self._ipc)
        except OSError as e:
            log.warning("Failed to remove mpv IPC socket %s: %s", self._ipc or "", e)

        self._proc = None
        self._ipc = None
        self._current_url = None
        
        if self._on_stopped_callback:
            self._on_stopped_callback()

    def is_running(self) -> bool:
        """Check if any MPV player is running (external or embedded)"""
        if self._proc is not None:
            # Check if the process is still alive
            if self._proc.poll() is None:
                return True
            else:
                # Process died, clean up
                self._cleanup_external()
                return False
        # Check if embedded player is ready
        return self.mpv_widget.is_ready

    def _cleanup_external(self):
        """Clean up external MPV resources"""
        if self._ipc and os.path.exists(self._ipc):
            try:
                os.remove(self._ipc)
            except OSError:
                pass
        self._proc = None
        self._ipc = None
        self._current_url = None

    def cycle_pause(self):
        """Toggle play/pause for external MPV or embedded"""
        if self._ipc:
            mpv_send_cmd(self._ipc, ["cycle", "pause"])
        else:
            # Embedded path
            try:
                self.mpv_widget.pause_toggle()
            except Exception:
                pass

    def seek(self, secs: int):
        """Seek for external MPV or embedded"""
        if self._ipc:
            mpv_send_cmd(self._ipc, ["seek", secs, "relative"])
        else:
            try:
                self.mpv_widget.seek(secs)
            except Exception:
                pass

    def change_speed(self, delta: float):
        """Change playback speed for external MPV or embedded"""
        if self._ipc:
            try:
                self._speed = max(0.1, min(4.0, self._speed + delta))
            except Exception:
                self._speed = 1.0
            mpv_send_cmd(self._ipc, ["set_property", "speed", round(self._speed, 2)])
        else:
            # embedded
            try:
                self._speed = max(0.1, min(4.0, self._speed + delta))
            except Exception:
                self._speed = 1.0
            try:
                self.mpv_widget.set_speed(self._speed)
            except Exception:
                pass

    def stop(self):
        """Stop external MPV or embedded"""
        # Embedded stop
        if not self._ipc:
            try:
                self.mpv_widget.stop()
            except Exception:
                pass
            return
        # External path: prefer quit over kill where possible
        if self._ipc:
            mpv_send_cmd(self._ipc, ["quit"])
        proc = self._proc
        if proc:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._proc = None
        self._ipc = None

    def copy_timestamp(self) -> str | None:
        """Get current timestamp for external MPV or embedded and return URL with timestamp"""
        pos = 0
        if self._ipc:
            # Ask external mpv for current playback position
            try:
                resp = mpv_send_cmd(self._ipc, ["get_property", "time-pos"])
                if isinstance(resp, dict) and "data" in resp:
                    v = resp.get("data")
                    if isinstance(v, (int, float)):
                        pos = int(v)
            except Exception:
                pos = 0
        else:
            # Embedded mpv
            try:
                pos = int(self.mpv_widget.current_time())
            except Exception:
                pos = 0
        
        url = self._current_url or ""
        if not url and self._ipc:
            # Try to get from MPV path property as fallback
            try:
                resp2 = mpv_send_cmd(self._ipc, ["get_property", "path"])
                if isinstance(resp2, dict) and isinstance(resp2.get("data"), str):
                    url = str(resp2["data"])
            except Exception:
                pass
        
        if not url:
            return None
        
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}t={pos}s"

    def copy_timestamp_to_clipboard(self) -> bool:
        """Copy the current timestamp URL to clipboard (Wayland-safe)"""
        timestamp_url = self.copy_timestamp()
        if not timestamp_url:
            return False
        
        try:
            disp = Gdk.Display.get_default()
            if not disp:
                return False
            clipboard = disp.get_clipboard()
            
            # Store provider to avoid GC on Wayland
            self._clipboard_provider = Gdk.ContentProvider.new_for_value(timestamp_url)
            clipboard.set_content(self._clipboard_provider)
            return True
        except Exception:
            # Fallback to primary
            try:
                if disp:
                    primary = disp.get_primary_clipboard()
                    if primary:
                        self._clipboard_provider_primary = Gdk.ContentProvider.new_for_value(timestamp_url)
                        primary.set_content(self._clipboard_provider_primary)
                return True
            except Exception:
                pass
        return False

    def cleanup(self):
        """Cleanup all resources"""
        if self._proc:
            try:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
            except Exception:
                pass
        if self._ipc and os.path.exists(self._ipc):
            try:
                os.remove(self._ipc)
            except Exception:
                pass
        self._proc = None
        self._ipc = None
        self._current_url = None