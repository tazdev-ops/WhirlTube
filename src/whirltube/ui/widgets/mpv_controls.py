"""MPV controls header bar widget with progress bar and volume control."""
from __future__ import annotations

import logging
import threading
import time

import gi
gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk, Gio, GLib

from ...services.playback import PlaybackService

log = logging.getLogger(__name__)


class MpvControls(Adw.Bin):
    """MPV controls header bar widget with progress bar and volume control"""
    
    def __init__(self, playback_service: PlaybackService) -> None:
        super().__init__()
        
        self._playback_service = playback_service
        
        # Create the header bar for MPV controls
        self.ctrl_bar = Adw.HeaderBar()
        self.ctrl_bar.set_title_widget(Gtk.Label(label="MPV Controls", css_classes=["dim-label"]))
        
        # Progress bar (for external MPV via IPC)
        self.progress_bar = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL,
            hexpand=True
        )
        self.progress_bar.set_range(0, 100)
        self.progress_bar.set_draw_value(False)
        self.progress_bar.connect("value-changed", self._on_seek)
        self.progress_bar.set_visible(False)  # Hidden by default
        
        # Time labels
        self.time_label = Gtk.Label(label="0:00 / 0:00")
        self.time_label.add_css_class("caption")
        self.time_label.set_visible(False)  # Hidden by default
        
        # Volume slider
        self.volume_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL
        )
        self.volume_slider.set_range(0, 100)
        self.volume_slider.set_value(100)
        self.volume_slider.set_size_request(100, -1)
        self.volume_slider.connect("value-changed", self._on_volume_change)
        self.volume_slider.set_visible(False)  # Hidden by default
        
        # Control buttons: Seek -10, Play/Pause, Seek +10, Speed -, Speed +, Stop, Copy TS
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
        
        # Pack controls
        # Left side: Progress controls
        left_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        left_box.append(self.time_label)
        left_box.append(self.progress_bar)
        self.ctrl_bar.pack_start(left_box)
        
        # Right side: Buttons
        self.ctrl_bar.pack_end(self.btn_stop_mpv)
        self.ctrl_bar.pack_end(self.btn_copy_ts)
        self.ctrl_bar.pack_end(self.btn_speed_up)
        self.ctrl_bar.pack_end(self.btn_speed_down)
        self.ctrl_bar.pack_end(self.btn_seek_fwd)
        self.ctrl_bar.pack_end(self.btn_play_pause)
        self.ctrl_bar.pack_end(self.btn_seek_back)
        
        # Volume control (packed separately)
        vol_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        vol_box.append(Gtk.Label(label="🔊"))
        vol_box.append(self.volume_slider)
        self.ctrl_bar.pack_end(vol_box)
        
        # Initially hidden
        self.ctrl_bar.set_visible(False)
        
        # Start property polling for external MPV
        self._start_ipc_polling()
    
    def _start_ipc_polling(self):
        """Poll MPV IPC for time-pos, duration, etc. using existing mpv_send_cmd"""
        def poll():
            while True:
                # Check if we have an IPC connection
                ipc_path = self._playback_service.get_ipc_path()
                if not ipc_path or not self._playback_service.is_running():
                    time.sleep(0.5)
                    continue
                
                try:
                    # Get time position and duration using existing method
                    time_pos = self._playback_service.get_ipc_property("time-pos") or 0
                    duration = self._playback_service.get_ipc_property("duration") or 0
                    pause = self._playback_service.get_ipc_property("pause") or False
                    
                    # Update UI on main thread
                    GLib.idle_add(self._update_progress, time_pos, duration, pause)
                except Exception as e:
                    log.debug(f"IPC polling error: {e}")
                
                time.sleep(0.5)
        
        threading.Thread(target=poll, daemon=True).start()
    
    def _update_progress(self, time_pos: float, duration: float, paused: bool):
        """Update progress bar (on main thread)"""
        if duration > 0:
            fraction = (time_pos / duration) * 100
            self.progress_bar.set_value(fraction)
            
            t_str = self._format_time(time_pos)
            d_str = self._format_time(duration)
            self.time_label.set_text(f"{t_str} / {d_str}")
            
            # Show progress controls
            self.progress_bar.set_visible(True)
            self.time_label.set_visible(True)
        else:
            # Hide progress controls when no duration
            self.progress_bar.set_visible(False)
            self.time_label.set_visible(False)
        
        # Update play/pause button icon
        if paused:
            self.btn_play_pause.set_icon_name("media-playback-start-symbolic")
        else:
            self.btn_play_pause.set_icon_name("media-playback-pause-symbolic")
    
    def _format_time(self, seconds: float) -> str:
        """Format seconds as H:MM:SS or M:SS"""
        s = int(seconds)
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        if h:
            return f"{h}:{m:02}:{sec:02}"
        return f"{m}:{sec:02}"
    
    def _on_seek(self, scale: Gtk.Scale):
        """Handle progress bar seeking"""
        ipc_path = self._playback_service.get_ipc_path()
        if not ipc_path:
            return
        
        duration_val = self._playback_service.get_ipc_property("duration")
        if duration_val and duration_val > 0:
            fraction = scale.get_value() / 100
            target_time = duration_val * fraction
            from ...player import mpv_send_cmd
            mpv_send_cmd(ipc_path, ["seek", str(target_time), "absolute"])
    
    def _on_volume_change(self, scale: Gtk.Scale):
        """Handle volume slider"""
        vol = int(scale.get_value())
        ipc_path = self._playback_service.get_ipc_path()
        if ipc_path:
            from ...player import mpv_send_cmd
            mpv_send_cmd(ipc_path, ["set_property", "volume", vol])
    
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
    
    def set_ipc_socket(self, socket_path: str | None):
        """Set IPC socket path for external MPV"""
        self._ipc_socket_path = socket_path
        # No need to reconnect client since we don't store an IPC client anymore