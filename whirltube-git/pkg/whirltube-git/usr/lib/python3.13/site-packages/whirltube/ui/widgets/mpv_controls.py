from __future__ import annotations

import gi
gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk, Gio

from ...services.playback import PlaybackService

import logging
log = logging.getLogger(__name__)

class MpvControls(Adw.Bin):
    """MPV controls header bar widget"""
    
    def __init__(self, playback_service: PlaybackService) -> None:
        super().__init__()
        
        self._playback_service = playback_service
        
        # Create the header bar for MPV controls
        self.ctrl_bar = Adw.HeaderBar()
        self.ctrl_bar.set_title_widget(Gtk.Label(label="MPV Controls", css_classes=["dim-label"]))
        
        # Buttons: Seek -10, Play/Pause, Seek +10, Speed -, Speed +, Stop, Copy TS
        self.btn_seek_back = Gtk.Button(icon_name="media-seek-backward-symbolic")
        self.btn_play_pause = Gtk.Button(icon_name="media-playback-pause-symbolic")
        self.btn_seek_fwd = Gtk.Button(icon_name="media-seek-forward-symbolic")
        self.btn_speed_down = Gtk.Button(label="Speed -")
        self.btn_speed_up = Gtk.Button(label="Speed +")
        self.btn_stop_mpv = Gtk.Button(icon_name="media-playback-stop-symbolic")
        self.btn_copy_ts = Gtk.Button(icon_name="edit-copy-symbolic")
        self.btn_copy_ts.set_tooltip_text("Copy URL at current time (T)")
        
        # Connect button signals to playback service methods
        self.btn_seek_back.connect("clicked", self._on_seek_back_clicked)
        self.btn_play_pause.connect("clicked", self._on_play_pause_clicked)
        self.btn_seek_fwd.connect("clicked", self._on_seek_fwd_clicked)
        self.btn_speed_down.connect("clicked", self._on_speed_down_clicked)
        self.btn_speed_up.connect("clicked", self._on_speed_up_clicked)
        self.btn_stop_mpv.connect("clicked", self._on_stop_clicked)
        self.btn_copy_ts.connect("clicked", self._on_copy_ts_clicked)
        
        # Pack controls on the right
        self.ctrl_bar.pack_end(self.btn_stop_mpv)
        self.ctrl_bar.pack_end(self.btn_copy_ts)
        self.ctrl_bar.pack_end(self.btn_speed_up)
        self.ctrl_bar.pack_end(self.btn_speed_down)
        self.ctrl_bar.pack_end(self.btn_seek_fwd)
        self.ctrl_bar.pack_end(self.btn_play_pause)
        self.ctrl_bar.pack_end(self.btn_seek_back)
        
        # Initially hidden
        self.ctrl_bar.set_visible(False)
    
    def _on_seek_back_clicked(self, button) -> None:
        """Handle seek backward button click"""
        self._playback_service.seek(-10)
    
    def _on_play_pause_clicked(self, button) -> None:
        """Handle play/pause button click"""
        self._playback_service.cycle_pause()
    
    def _on_seek_fwd_clicked(self, button) -> None:
        """Handle seek forward button click"""
        self._playback_service.seek(10)
    
    def _on_speed_down_clicked(self, button) -> None:
        """Handle speed down button click"""
        self._playback_service.change_speed(-0.1)
    
    def _on_speed_up_clicked(self, button) -> None:
        """Handle speed up button click"""
        self._playback_service.change_speed(0.1)
    
    def _on_stop_clicked(self, button) -> None:
        """Handle stop button click"""
        self._playback_service.stop()
    
    def _on_copy_ts_clicked(self, button) -> None:
        """Handle copy timestamp button click"""
        self._playback_service.copy_timestamp_to_clipboard()
    
    def set_visible(self, visible: bool) -> None:
        """Set visibility of the control bar"""
        self.ctrl_bar.set_visible(visible)
    
    def get_ctrl_bar(self):
        """Get the underlying control bar"""
        return self.ctrl_bar
    
    def update_controls_visibility(self, is_mpv_running: bool, autohide_enabled: bool, 
                                 current_stack_page: str | None = None) -> None:
        """Update visibility based on MPV state and settings"""
        visible = False
        if is_mpv_running:
            # Honor autohide preference: show only on player view when enabled
            if autohide_enabled:
                visible = (current_stack_page == "player")
            else:
                visible = True
        
        self.set_visible(visible)
    
    def add_actions_to_window(self, window: Adw.ApplicationWindow) -> None:
        """Add MPV actions to the window for keyboard shortcuts"""
        # Define actions
        a_play_pause = Gio.SimpleAction.new("mpv_play_pause", None)
        a_play_pause.connect("activate", lambda *_: self._playback_service.cycle_pause())
        window.add_action(a_play_pause)

        a_seek_back = Gio.SimpleAction.new("mpv_seek_back", None)
        a_seek_back.connect("activate", lambda *_: self._playback_service.seek(-10))
        window.add_action(a_seek_back)

        a_seek_fwd = Gio.SimpleAction.new("mpv_seek_fwd", None)
        a_seek_fwd.connect("activate", lambda *_: self._playback_service.seek(10))
        window.add_action(a_seek_fwd)

        a_speed_down = Gio.SimpleAction.new("mpv_speed_down", None)
        a_speed_down.connect("activate", lambda *_: self._playback_service.change_speed(-0.1))
        window.add_action(a_speed_down)

        a_speed_up = Gio.SimpleAction.new("mpv_speed_up", None)
        a_speed_up.connect("activate", lambda *_: self._playback_service.change_speed(0.1))
        window.add_action(a_speed_up)

        a_copy_ts = Gio.SimpleAction.new("mpv_copy_ts", None)
        a_copy_ts.connect("activate", lambda *_: self._playback_service.copy_timestamp_to_clipboard())
        window.add_action(a_copy_ts)

        a_stop = Gio.SimpleAction.new("stop_mpv", None)
        a_stop.connect("activate", lambda *_: self._playback_service.stop())
        a_stop.set_enabled(False)  # only enabled when mpv running initially
        window.add_action(a_stop)
        
        # Store reference to stop action to enable/disable it based on MPV state
        window._mpv_stop_action = a_stop
    
    def install_accelerators(self, application: Gio.Application) -> None:
        """Install keyboard accelerators for MPV actions"""
        # YouTube-like keys: j/k/l and +/- for speed, x to stop
        if application:
            application.set_accels_for_action("win.mpv_play_pause", ["K", "k"])
            application.set_accels_for_action("win.mpv_seek_back", ["J", "j"])
            application.set_accels_for_action("win.mpv_seek_fwd", ["L", "l"])
            application.set_accels_for_action("win.mpv_speed_down", ["minus", "KP_Subtract"])
            application.set_accels_for_action("win.mpv_speed_up", ["equal", "KP_Add"])
            application.set_accels_for_action("win.mpv_copy_ts", ["T", "t"])
            application.set_accels_for_action("win.stop_mpv", ["X", "x"])
    
    def handle_key_press(self, keyval: int, keycode: int, state) -> bool:
        """Handle key press events for MPV controls"""
        import gi
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
        
        # Only handle when MPV is running
        if not self._playback_service.is_running():
            return False
            
        k = Gdk.keyval_name(keyval) or ""
        k = k.lower()
        handled = False
        
        if k == "j":
            self._playback_service.seek(-10)
            handled = True
        elif k == "k":
            self._playback_service.cycle_pause()
            handled = True
        elif k == "l":
            self._playback_service.seek(10)
            handled = True
        elif k in ("minus", "kp_subtract"):
            self._playback_service.change_speed(-0.1)
            handled = True
        elif k in ("equal", "kp_add", "plus"):
            self._playback_service.change_speed(0.1)
            handled = True
        elif k == "x":
            self._playback_service.stop()
            handled = True
        elif k == "t":
            self._playback_service.copy_timestamp_to_clipboard()
            handled = True
            
        return handled