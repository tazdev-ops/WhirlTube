from __future__ import annotations

import logging
from typing import Optional, Mapping, Any

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gtk

log = logging.getLogger(__name__)

try:
    gi.require_version("GdkX11", "4.0")
    from gi.repository import GdkX11  # type: ignore
except Exception:
    GdkX11 = None  # type: ignore

try:
    import mpv  # type: ignore
except Exception:
    mpv = None  # type: ignore


class MpvWidget(Gtk.Box):
    """
    Attempt to embed mpv into a GTK widget on X11.
    On Wayland (or missing python-mpv), shows a fallback label.
    """
    # Note: Works on X11. Wayland falls back to label (external mpv is used).

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_hexpand(True)
        self.set_vexpand(True)

        self._area = Gtk.DrawingArea()
        self._area.set_hexpand(True)
        self._area.set_vexpand(True)
        self.append(self._area)

        self._mpv: mpv.MPV | None = None
        self._ready = False

        self._fallback = Gtk.Label(
            label="Embedded playback not available on this backend.\nUsing external MPV instead.",
            wrap=True,
            justify=Gtk.Justification.CENTER,
        )
        self._fallback.set_visible(False)
        self.append(self._fallback)

        self._area.connect("realize", self._on_realize)
        self._area.connect("unrealize", self._on_unrealize)

    # --- GTK lifecycle ---
    def _on_realize(self, *_args) -> None:
        if mpv is None or GdkX11 is None:
            self._fallback.set_visible(True)
            log.info("mpv embedding not available (python-mpv or X11 missing)")
            return
        native = self._area.get_native()
        if native is None:
            self._fallback.set_visible(True)
            return
        surface = native.get_surface()
        if surface is None or not isinstance(surface, GdkX11.X11Surface):
            self._fallback.set_visible(True)
            log.info("Not an X11 surface; cannot embed mpv.")
            return
        xid = GdkX11.X11Surface.get_xid(surface)
        try:
            # Set locale for libmpv (client.h requirement)
            try:
                import locale
                locale.setlocale(locale.LC_NUMERIC, "C")
            except Exception:
                pass
            
            # Basic, usable defaults. More can be set later via setters below.
            self._mpv = mpv.MPV(
                wid=str(xid),
                ytdl=True, osc=True, input_default_bindings=True, config=True, keep_open=True,
            )
            
            # Use property observers instead of polling for better performance
            @self._mpv.property_observer('time-pos')
            def _time_observer(_name, val):
                # This will be called whenever time-pos changes
                # Hook into controls/overlay as needed
                pass

            @self._mpv.property_observer('pause')
            def _pause_observer(_name, paused):
                # This will be called whenever pause state changes
                pass
            
            self._ready = True
            self._fallback.set_visible(False)
        except Exception as e:
            log.exception("Failed to create mpv instance: %s", e)
            self._fallback.set_visible(True)

    def _on_unrealize(self, *_args) -> None:
        if self._mpv:
            try:
                self._mpv.terminate()
            except Exception:
                pass
        self._mpv = None
        self._ready = False

    # --- Capability ---
    @property
    def is_ready(self) -> bool:
        return self._ready and self._mpv is not None

    # --- Option setters (call before play() ideally) ---
    def set_ytdl_format(self, fmt: Optional[str]) -> None:
        if not self.is_ready or fmt is None:
            return
        try:
            self._mpv["ytdl-format"] = fmt  # type: ignore[index]
        except Exception:
            pass

    def set_ytdl_raw_options(self, opts: Optional[Mapping[str, Any]]) -> None:
        """
        opts example: {"cookies-from-browser": "firefox+gnomekeyring:default::Work", "proxy": "http://..."}
        """
        if not self.is_ready or not opts:
            return
        try:
            # python-mpv accepts dict for ytdl-raw-options
            self._mpv["ytdl-raw-options"] = dict(opts)  # type: ignore[index]
        except Exception:
            pass

    # --- Playback controls ---
    def play(self, url: str) -> bool:
        if self._ready and self._mpv is not None:
            try:
                self._mpv.play(url)  # type: ignore[attr-defined]
                return True
            except Exception:
                log.exception("mpv.play failed")
                return False
        return False

    def pause_toggle(self) -> None:
        if not self.is_ready:
            return
        try:
            self._mpv.command("cycle", "pause")  # type: ignore[attr-defined]
        except Exception:
            pass

    def seek(self, secs: float) -> None:
        if not self.is_ready:
            return
        try:
            self._mpv.command("seek", secs, "relative")  # type: ignore[attr-defined]
        except Exception:
            pass

    def set_speed(self, speed: float) -> None:
        if not self.is_ready:
            return
        try:
            self._mpv["speed"] = max(0.1, min(4.0, float(speed)))  # type: ignore[index]
        except Exception:
            pass

    def current_time(self) -> int:
        if not self.is_ready:
            return 0
        try:
            # python-mpv maps properties to attributes
            pos = getattr(self._mpv, "time_pos", None)
            return int(pos or 0)
        except Exception:
            return 0

    def stop(self) -> None:
        if not self.is_ready:
            return
        try:
            self._mpv.command("stop")  # type: ignore[attr-defined]
        except Exception:
            pass
