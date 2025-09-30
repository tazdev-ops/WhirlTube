from __future__ import annotations

import logging

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
            self._mpv = mpv.MPV(wid=str(xid), ytdl=True, osc=True)
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

    def play(self, url: str) -> bool:
        if self._ready and self._mpv is not None:
            try:
                self._mpv.play(url)
                return True
            except Exception:
                log.exception("mpv.play failed")
                return False
        return False
