from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import subprocess
import shlex
import os
import tempfile
import secrets
from ..player import start_mpv, has_mpv
import logging

log = logging.getLogger(__name__)

@dataclass
class MpvConfig:
    quality: str | None
    cookies_browser: str | None
    cookies_keyring: str | None
    cookies_profile: str | None
    cookies_container: str | None
    http_proxy: str | None
    fullscreen: bool
    custom_args: str | None
    sb_enabled: bool
    sb_mode: str
    sb_categories: str


class MpvLauncher:
    def __init__(self, assets_dir: Path):
        self.assets_dir = assets_dir
    
    def _build_cookie_spec(self, cfg: MpvConfig) -> str | None:
        if not cfg.cookies_browser:
            return None
        val = cfg.cookies_browser
        if cfg.cookies_keyring:
            val += f"+{cfg.cookies_keyring}"
        if cfg.cookies_profile and cfg.cookies_container:
            val += f":{cfg.cookies_profile}::{cfg.cookies_container}"
        elif cfg.cookies_profile:
            val += f":{cfg.cookies_profile}"
        elif cfg.cookies_container:
            val += f"::{cfg.cookies_container}"
        return val
    
    def build_args(self, url: str, config: MpvConfig, playback_mode: str = "external", extra_mpv_args: list[str] | None = None) -> tuple[list[str], str | None, subprocess.Popen | None]:
        if not has_mpv():
            log.error("MPV not found in PATH")
            return [], None, None
        
        args = ["mpv", "--force-window=yes"]
        
        # Quality
        if config.quality and config.quality != "auto":
            try:
                h = int(config.quality)
                quality_format = f'bv*[height<={h}]+ba/b[height<={h}]'
                args.append(f'--ytdl-format={quality_format}')
            except Exception:
                pass
        
        # Fullscreen options
        from ..player import mpv_supports_option
        session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
        is_wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))
        
        if is_wayland and mpv_supports_option("wayland-app-id"):
            args.append("--wayland-app-id=org.whirltube.WhirlTube")
        if not is_wayland and mpv_supports_option("class"):
            args.append("--class=org.whirltube.WhirlTube")
        
        # Add custom mpv args if provided
        if config.custom_args:
            try:
                custom_args_list = shlex.split(config.custom_args)
                args.extend(custom_args_list)
            except Exception:
                log.warning("Failed to parse MPV args; launching without user args")
        
        # Add extra MPV args if provided
        if extra_mpv_args:
            args.extend(extra_mpv_args)
        
        # Cookie and proxy handling via ytdl-raw-options
        ytdl_raw_parts = []
        
        if config.cookies_browser:
            cookie_spec = self._build_cookie_spec(config)
            if cookie_spec:
                ytdl_raw_parts.append(f"cookies-from-browser={cookie_spec}")
        
        if config.http_proxy:
            ytdl_raw_parts.append(f"proxy={config.http_proxy}")
        
        if ytdl_raw_parts:
            args.append(f"--ytdl-raw-options={','.join(ytdl_raw_parts)}")
        
        # SponsorBlock for external playback mode
        if config.sb_enabled and playback_mode != "embedded":
            script_path = self.assets_dir / "scripts" / "sponsorblock.lua"
            if script_path.exists():
                args += ["--script", str(script_path)]
                # Map to Lua script config
                sb_opts = [
                    f"sponsorblock-categories={config.sb_categories or 'sponsor,intro'}",
                    f"sponsorblock-skip_categories={config.sb_categories if config.sb_mode=='skip' else ''}",
                    "sponsorblock-local_database=no",
                    "sponsorblock-make_chapters=yes",
                ]
                args.append("--script-opts=" + ",".join(sb_opts))
        
        args.append(url)
        
        # Create unique IPC socket path
        rnd = secrets.token_hex(4)
        ipc_dir = Path(tempfile.gettempdir())
        ipc_path = str(ipc_dir / f"whirltube-mpv-{os.getpid()}-{rnd}.sock")
        log_file = str(ipc_dir / f"whirltube-mpv-{os.getpid()}-{rnd}.log") if os.environ.get("WHIRLTUBE_DEBUG") else None
        
        args.insert(2, f"--input-ipc-server={ipc_path}")  # Insert IPC after basic options
        
        # Proxy env
        extra_env = {}
        if config.http_proxy:
            extra_env["http_proxy"] = config.http_proxy
            extra_env["https_proxy"] = config.http_proxy
        
        # Launch MPV
        try:
            proc = start_mpv(
                url,
                extra_args=args[3:],  # Skip mpv and --force-window=yes, --input-ipc-server from front
                ipc_server_path=ipc_path,
                extra_env=extra_env,
                log_file_path=log_file,
            )
            return args, ipc_path, proc
        except Exception as e:
            log.error("Failed to start mpv: %s", e)
            if os.environ.get("WHIRLTUBE_DEBUG") and log_file:
                log.error(f"Failed to start mpv. See log: {log_file}")
            else:
                log.error("Failed to start mpv. See logs for details.")
            return [], None, None

    def launch(self, args: list[str], ipc_path: str, extra_env: dict | None = None, url: str = "") -> subprocess.Popen | None:
        try:
            proc = start_mpv(
                url,
                extra_args=args,
                ipc_server_path=ipc_path,
                extra_env=extra_env,
            )
            return proc
        except Exception as e:
            log.error("Failed to start mpv: %s", e)
            return None