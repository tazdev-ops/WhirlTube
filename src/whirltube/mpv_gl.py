from __future__ import annotations
import os, ctypes
from ctypes import util, c_void_p, c_char_p, byref
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk, Gdk, GLib

try:
    import mpv  # python-mpv
except Exception:
    mpv = None  # type: ignore

# Optional: use PyOpenGL to query current FBO; fallback to 0 if unavailable
try:
    from OpenGL import GL
    _HAVE_GL = True
except Exception:
    GL = None
    _HAVE_GL = False

def _get_proc_address_factory():
    # Prefer EGL on Wayland, fall back to GLX for X11
    egl = None
    glx = None
    try:
        path = util.find_library("EGL") or "libEGL.so.1"
        egl = ctypes.CDLL(path)
        egl.eglGetProcAddress.restype = c_void_p
        egl.eglGetProcAddress.argtypes = [c_char_p]
    except Exception:
        egl = None
    try:
        path = util.find_library("GL") or "libGL.so.1"
        glx = ctypes.CDLL(path)
        # Not always present on Wayland, hence the try/except
        if hasattr(glx, "glXGetProcAddressARB"):
            glx.glXGetProcAddressARB.restype = c_void_p
            glx.glXGetProcAddressARB.argtypes = [c_char_p]
        else:
            glx = None
    except Exception:
        glx = None

    def get_proc_address(name: bytes) -> int | None:
        # mpv calls this with bytes already (C ABI)
        if egl is not None:
            ptr = egl.eglGetProcAddress(name)
            if ptr:
                return ptr
        if glx is not None:
            try:
                return glx.glXGetProcAddressARB(name)
            except Exception:
                return None
        return None

    # python-mpv expects a Python callable; it casts to (const char*) -> void*
    return lambda sym: get_proc_address(sym if isinstance(sym, (bytes, bytearray)) else bytes(sym, "utf-8"))

class MpvGLWidget(Gtk.GLArea):
    """
    Wayland-safe embedded mpv using libmpv render API inside a GtkGLArea.
    Implements the same surface API as your old MpvWidget where possible.
    """
    def __init__(self) -> None:
        super().__init__()
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_auto_render(False)  # we control when to draw
        self._mpv: mpv.MPV | None = None
        self._glcb = None
        self._inited = False

        # Show a fallback label when lib/bindings missing
        if mpv is None:
            self.set_visible(False)
            self._fallback = Gtk.Label(label="mpv/libmpv not available")
            self.get_parent() and self.get_parent().append(self._fallback)

        self.connect("realize", self._on_realize)
        self.connect("unrealize", self._on_unrealize)
        self.connect("render", self._on_render)

    # Capability
    @property
    def is_ready(self) -> bool:
        return bool(self._inited and self._mpv is not None)

    # Public controls mirrored from MpvWidget
    def set_ytdl_format(self, fmt: str | None) -> None:
        if not self.is_ready or fmt is None:
            return
        try:
            self._mpv["ytdl-format"] = fmt  # type: ignore[index]
        except Exception:
            pass

    def set_ytdl_raw_options(self, opts: dict | None) -> None:
        if not self.is_ready or not opts:
            return
        try:
            self._mpv["ytdl-raw-options"] = dict(opts)  # type: ignore[index]
        except Exception:
            pass

    def play(self, url: str) -> bool:
        if not self.is_ready:
            return False
        try:
            self._mpv.play(url)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    def pause_toggle(self) -> None:
        if self._mpv is not None:
            try:
                self._mpv.command("cycle", "pause")  # type: ignore[attr-defined]
            except Exception:
                pass

    def seek(self, secs: float) -> None:
        if self._mpv is not None:
            try:
                self._mpv.command("seek", secs, "relative")  # type: ignore[attr-defined]
            except Exception:
                pass

    def set_speed(self, speed: float) -> None:
        if self._mpv is not None:
            try:
                self._mpv["speed"] = max(0.1, min(4.0, float(speed)))  # type: ignore[index]
            except Exception:
                pass

    def current_time(self) -> int:
        if self._mpv is None:
            return 0
        try:
            pos = getattr(self._mpv, "time_pos", None)
            return int(pos or 0)
        except Exception:
            return 0

    def stop(self) -> None:
        if self._mpv is not None:
            try:
                self._mpv.command("stop")  # type: ignore[attr-defined]
            except Exception:
                pass

    # Internals
    def _on_realize(self, *_a) -> None:
        if mpv is None or self._inited:
            return
        self.make_current()
        # Create mpv instance in OpenGL callback mode
        self._mpv = mpv.MPV(
            opengl_cb=True,         # use render API
            ytdl=True,
            osc=True,
            config=True,
            input_default_bindings=True,
            keep_open=True,
            vo="gpu",               # windowless when opengl_cb=True
            hwdec="auto-safe",
        )
        # Wrap render callback API
        self._glcb = mpv.OpenGLCB(self._mpv)
        get_proc = _get_proc_address_factory()

        # Init GL bridging
        self._glcb.init_gl(get_proc)

        # When mpv has a new frame or needs redraw, update the GTK widget
        def _mpv_needs_update():
            # Called from mpv thread; schedule redraw on GTK main
            GLib.idle_add(self.queue_render)
        self._glcb.set_update_callback(_mpv_needs_update)

        self._inited = True

    def _on_unrealize(self, *_a) -> None:
        if self._glcb is not None:
            try:
                self.make_current()
                self._glcb.uninit_gl()
            except Exception:
                pass
        if self._mpv is not None:
            try:
                self._mpv.terminate()  # graceful shutdown
            except Exception:
                pass
        self._glcb = None
        self._mpv = None
        self._inited = False

    def _on_render(self, _area: Gtk.GLArea, _ctx: Gdk.GLContext) -> bool:
        if not self._glcb:
            return False
        # Determine current framebuffer and size
        if _HAVE_GL:
            fbo = GL.glGetIntegerv(GL.GL_FRAMEBUFFER_BINDING)
            if isinstance(fbo, (list, tuple)):
                fbo = fbo[0]
            fbo_id = int(fbo or 0)
        else:
            fbo_id = 0  # default framebuffer
        w = max(1, int(self.get_allocated_width() * self.get_scale_factor()))
        h = max(1, int(self.get_allocated_height() * self.get_scale_factor()))
        try:
            # mpv will render OSD/OSC if enabled; flip Y matches GL default FBO
            self._glcb.draw(fbo_id, w, h)
        except Exception:
            # Swallow transient draw errors to avoid GTK warnings
            pass
        return True