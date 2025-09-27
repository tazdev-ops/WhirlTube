from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

APP_ID = "org.whirltube.WhirlTube"
log = logging.getLogger(__name__)


def _setup_logging() -> None:
    level = logging.DEBUG if os.environ.get("WHIRLTUBE_DEBUG") else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    # Lazy import GTK libs so importing this module doesn't require GI
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Adw, Gdk, Gio, Gtk

    def _register_icon_theme_path() -> None:
        # Add bundled icons to the icon theme so "whirltube" resolves even from wheels.
        try:
            base = Path(__file__).resolve().parent  # src/whirltube
            icon_root = base / "assets" / "icons" / "hicolor"
            if icon_root.exists():
                display = Gdk.Display.get_default()
                if display is not None:
                    theme = Gtk.IconTheme.get_for_display(display)
                    theme.add_search_path(str(icon_root))
                    log.debug("Registered icon theme path: %s", icon_root)
        except Exception as e:
            log.debug("Icon theme path registration skipped: %s", e)

    class App(Adw.Application):
        def __init__(self) -> None:
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
            self._create_actions()

        def do_activate(self) -> None:  # type: ignore[override]
            _register_icon_theme_path()
            win = self.props.active_window
            if not win:
                # Import the heavy window module only when activating
                from .window import MainWindow
                win = MainWindow(app=self)
            win.present()

        def _create_actions(self) -> None:
            action_quit = Gio.SimpleAction.new("quit", None)
            action_quit.connect("activate", self._on_quit)
            self.add_action(action_quit)
            self.set_accels_for_action("app.quit", ["<Primary>q"])

        def _on_quit(self, *args) -> None:
            self.quit()

    Adw.init()
    app = App()
    return app.run(argv or sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
