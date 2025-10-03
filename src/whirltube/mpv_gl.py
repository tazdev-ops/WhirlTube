from __future__ import annotations

import logging
import locale
from typing import Optional, Mapping, Any

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

log = logging.getLogger(__name__)

try:
    import mpv  # python-mpv must have opengl-cb
    from OpenGL import GL
    HAS_GL = True
except Exception:
    HAS_GL = False
    mpv = None  # type: ignore

class MpvGLWidget(Gtk.GLArea):
    def __init__(self):
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._mpv: Optional[mpv.MPV] = None
        self._gl_cb: Optional[mpv.GLCallback] = None
        self._ready = False
        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render", self._on_render)

    def _on_realize(self, *_a):
        if not HAS_GL:
            log.warning("python-mpv or PyOpenGL missing; GL embed unavailable")
            return
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except Exception:
            pass
        self.make_current()
        if self.get_error():
            log.error("GLArea error; cannot initialize")
            return
        try:
            # Use 'gpu' vo for OpenGL callback; prefer GLES on Wayland
            import os
            session = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
            is_wayland = session == "wayland" or bool(os.environ.get("WAYLAND_DISPLAY"))

            mpv_kwargs = dict(
                vo="gpu",
                keep_open=True,
                idle=True,
                profile="gpu-hq",
                osc=True,
                ytdl=True,
                input_default_bindings=True,
                config=True,
            )
            # On Wayland, tell mpv to use GLES (GLArea often uses EGL/GLES)
            if is_wayland:
                mpv_kwargs["opengl_es"] = True

            self._mpv = mpv.MPV(**mpv_kwargs)
            self._gl_cb = mpv.GLCallback(self._mpv)

            def _get_proc_address(name: str) -> int:
                addr = self.get_proc_address(name)
                return addr or 0

            self._gl_cb.set_get_proc_address(_get_proc_address)
            self._gl_cb.set_update_callback(lambda: GLib.idle_add(self.queue_render))
            self._gl_cb.init_gl()
            self._ready = True
            log.info("MpvGLWidget initialized")
        except Exception as e:
            log.exception("Failed to init MpvGLWidget: %s", e)
            self._ready = False

    def _on_unrealize(self, *_a):
        try:
            if self._gl_cb:
                self.make_current()
                self._gl_cb.uninit_gl()
        except Exception:
            pass
        try:
            if self._mpv:
                self._mpv.terminate()
        except Exception:
            pass
        self._mpv = None
        self._gl_cb = None
        self._ready = False

    def _on_render(self, area: Gtk.GLArea, _ctx) -> bool:
        if not self._ready or not self._gl_cb:
            return False
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        GL.glViewport(0, 0, w, h)
        GL.glClearColor(0.05, 0.05, 0.05, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
        try:
            self._gl_cb.draw()
        except Exception as e:
            log.debug("GL draw failed: %s", e)
        return True

    @property
    def is_ready(self) -> bool:
        return bool(self._ready and self._mpv)

    def set_ytdl_format(self, fmt: Optional[str]) -> None:
        if self.is_ready and fmt:
            try:
                self._mpv["ytdl-format"] = fmt  # type: ignore[index]
            except Exception:
                pass

    def set_ytdl_raw_options(self, opts: Optional[Mapping[str, Any]]) -> None:
        if self.is_ready and opts:
            try:
                self._mpv["ytdl-raw-options"] = dict(opts)  # type: ignore[index]
            except Exception:
                pass

    def play(self, url: str) -> bool:
        if self.is_ready and self._mpv:
            try:
                self._mpv.play(url)  # type: ignore[attr-defined]
                return True
            except Exception as e:
                log.debug("mpv.play failed: %s", e)
        return False

    def pause_toggle(self) -> None:
        if self.is_ready:
            try:
                self._mpv.command("cycle", "pause")  # type: ignore[attr-defined]
            except Exception:
                pass

    def seek(self, secs: float) -> None:
        if self.is_ready:
            try:
                self._mpv.command("seek", secs, "relative")  # type: ignore[attr-defined]
            except Exception:
                pass

    def set_speed(self, speed: float) -> None:
        if self.is_ready:
            try:
                self._mpv["speed"] = max(0.1, min(4.0, float(speed)))  # type: ignore[index]
            except Exception:
                pass

    def current_time(self) -> int:
        if not self.is_ready:
            return 0
        try:
            pos = getattr(self._mpv, "time_pos", None)
            return int(pos or 0)
        except Exception:
            return 0

    def stop(self) -> None:
        if self.is_ready:
            try:
                self._mpv.command("stop")  # type: ignore[attr-defined]
            except Exception:
                pass
