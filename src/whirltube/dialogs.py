from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shlex

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk


@dataclass(slots=True)
class DownloadOptions:
    # quality
    quality_mode: str = "highest"  # highest | lowest | custom
    custom_format: str | None = None
    sort_string: str = ""  # yt-dlp -S format-sort string

    # subtitles
    write_subs: bool = False
    subs_langs: str = ""  # e.g. "en,es"
    write_auto_subs: bool = False
    subs_format: str = "vtt"  # vtt/srt/best

    # sponsorblock
    sb_mark: str = ""  # e.g. "sponsor,intro"
    sb_remove: str = ""  # e.g. "selfpromo"

    # embedding/thumbnail
    embed_metadata: bool = False
    embed_thumbnail: bool = False
    write_thumbnail: bool = False

    # cookies
    use_cookies: bool = False
    cookies_browser: str = ""  # firefox/chromium/brave/edge/...
    cookies_keyring: str = ""  # gnomekeyring/kwallet...
    cookies_profile: str = ""  # profile name/path
    cookies_container: str = ""  # firefox container name

    # network
    limit_rate: str = ""  # e.g. "4M"
    concurrent_fragments: int = 0  # yt-dlp -N
    impersonate: str = ""  # e.g. "chrome-110"

    # misc
    extra_flags: str = ""  # raw yt-dlp flags (forces subprocess)
    target_dir: Path | None = None

    def to_ydl_opts(self) -> dict:
        """Options mapping for Python API path (limited set)."""
        opts: dict = {
            "quiet": True,
            "nocheckcertificate": True,
            "merge_output_format": "mp4",
        }

        # quality
        if self.quality_mode == "highest":
            opts["format"] = "bv*+ba/b"
        elif self.quality_mode == "lowest":
            opts["format"] = "worst"
        elif self.quality_mode == "custom" and self.custom_format:
            opts["format"] = self.custom_format

        # format sort
        if self.sort_string.strip():
            opts["format_sort"] = self.sort_string.strip()

        # subtitles
        if self.write_subs:
            opts["writesubtitles"] = True
            if self.subs_langs.strip():
                langs = [s.strip() for s in self.subs_langs.split(",") if s.strip()]
                if langs:
                    opts["subtitleslangs"] = langs
            if self.write_auto_subs:
                opts["writeautomaticsub"] = True
            if self.subs_format:
                opts["subtitlesformat"] = self.subs_format

        # Note: many advanced flags are easier via CLI; see raw_cli_list().
        return opts

    def raw_cli_list(self) -> list[str]:
        """Build yt-dlp CLI args equivalent to all selected options."""
        parts: list[str] = []

        # quality
        if self.quality_mode == "highest":
            parts += ["-f", "bv*+ba/b"]
        elif self.quality_mode == "lowest":
            parts += ["-f", "worst"]
        elif self.quality_mode == "custom" and self.custom_format:
            parts += ["-f", self.custom_format]

        # format sort
        if self.sort_string.strip():
            parts += ["-S", self.sort_string.strip()]

        # subtitles
        if self.write_subs:
            parts += ["--write-subs"]
        if self.write_auto_subs:
            parts += ["--write-auto-subs"]
        if self.subs_langs.strip():
            parts += ["--sub-langs", self.subs_langs.strip()]
        if self.subs_format.strip():
            parts += ["--sub-format", self.subs_format.strip()]

        # sponsorblock
        if self.sb_mark.strip():
            parts += ["--sponsorblock-mark", self.sb_mark.strip()]
        if self.sb_remove.strip():
            parts += ["--sponsorblock-remove", self.sb_remove.strip()]

        # embedding / thumbnail
        if self.embed_metadata:
            parts += ["--embed-metadata"]
        if self.embed_thumbnail:
            parts += ["--embed-thumbnail"]
        if self.write_thumbnail:
            parts += ["--write-thumbnail"]

        # cookies
        if self.use_cookies and self.cookies_browser.strip():
            c = self.cookies_browser.strip()
            if self.cookies_keyring.strip():
                c += f"+{self.cookies_keyring.strip()}"
            if self.cookies_profile.strip() or self.cookies_container.strip():
                prof = self.cookies_profile.strip()
                cont = self.cookies_container.strip()
                c += f":{prof}"
                c += f"::{cont}" if cont else ""
            parts += ["--cookies-from-browser", c]

        # network
        if self.limit_rate.strip():
            parts += ["--limit-rate", self.limit_rate.strip()]
        if self.concurrent_fragments > 0:
            parts += ["-N", str(self.concurrent_fragments)]
        if self.impersonate.strip():
            parts += ["--impersonate", self.impersonate.strip()]

        # extra
        if self.extra_flags.strip():
            parts += shlex.split(self.extra_flags.strip())
        return parts


class DownloadOptionsWindow(Adw.Window):
    def __init__(self, parent: Gtk.Window, title: str) -> None:
        super().__init__(transient_for=parent, modal=True, title=f"Download: {title}")
        self.set_default_size(600, 700)

        root = Adw.ToolbarView()
        self.set_content(root)
        header = Adw.HeaderBar()
        root.add_top_bar(header)

        # Main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        
        # Quality tab
        quality_group = Adw.PreferencesGroup(title="Quality")
        main_box.append(quality_group)
        
        # Quality mode
        self.quality_mode = Adw.ComboRow(
            title="Quality",
            model=Gtk.StringList.new(["Highest", "Lowest", "Custom"]),
        )
        self.quality_mode.set_selected(0)
        quality_group.add(self.quality_mode)
        
        # Custom format (when quality=custom)
        self.custom_format_row = Adw.EntryRow(title="Custom format")
        self.custom_format_row.set_visible(False)
        quality_group.add(self.custom_format_row)
        
        # Sort string
        self.sort_string_row = Adw.EntryRow(title="Format sort string (e.g. res:1080,res)")
        quality_group.add(self.sort_string_row)
        
        # Subtitles group
        subs_group = Adw.PreferencesGroup(title="Subtitles")
        main_box.append(subs_group)
        
        self.write_subs = Adw.SwitchRow(title="Download subtitles")
        subs_group.add(self.write_subs)
        
        self.subs_langs = Adw.EntryRow(title="Subtitle languages (comma-separated)")
        self.subs_langs.set_text("en")
        subs_group.add(self.subs_langs)
        
        self.write_auto_subs = Adw.SwitchRow(title="Download auto-generated subtitles")
        subs_group.add(self.write_auto_subs)
        
        self.subs_format_row = Adw.ComboRow(
            title="Subtitle format",
            model=Gtk.StringList.new(["vtt", "srt", "best"]),
        )
        self.subs_format_row.set_selected(0)
        subs_group.add(self.subs_format_row)
        
        # Sponsorblock group
        sb_group = Adw.PreferencesGroup(title="SponsorBlock")
        main_box.append(sb_group)
        
        self.sb_mark_row = Adw.EntryRow(title="Categories to mark (comma-separated)")
        sb_group.add(self.sb_mark_row)
        
        self.sb_remove_row = Adw.EntryRow(title="Categories to remove (comma-separated)")
        sb_group.add(self.sb_remove_row)
        
        # Embedding group
        embed_group = Adw.PreferencesGroup(title="Embedding")
        main_box.append(embed_group)
        
        self.embed_metadata = Adw.SwitchRow(title="Embed metadata")
        embed_group.add(self.embed_metadata)
        
        self.embed_thumbnail = Adw.SwitchRow(title="Embed thumbnail")
        embed_group.add(self.embed_thumbnail)
        
        self.write_thumbnail = Adw.SwitchRow(title="Save thumbnail as separate file")
        embed_group.add(self.write_thumbnail)
        
        # Cookies group
        cookies_group = Adw.PreferencesGroup(title="Cookies")
        main_box.append(cookies_group)
        
        self.use_cookies = Adw.SwitchRow(title="Use cookies")
        cookies_group.add(self.use_cookies)
        
        self.cookies_browser = Adw.ComboRow(
            title="Browser",
            model=Gtk.StringList.new(["firefox", "chromium", "brave", "edge"]),
        )
        self.cookies_browser.set_selected(0)
        cookies_group.add(self.cookies_browser)
        
        self.cookies_keyring = Adw.EntryRow(title="Keyring (optional)")
        cookies_group.add(self.cookies_keyring)
        
        self.cookies_profile = Adw.EntryRow(title="Profile (optional)")
        cookies_group.add(self.cookies_profile)
        
        self.cookies_container = Adw.EntryRow(title="Container (Firefox; optional)")
        cookies_group.add(self.cookies_container)
        
        # Network group
        net_group = Adw.PreferencesGroup(title="Network")
        main_box.append(net_group)
        
        self.limit_rate = Adw.EntryRow(title="Rate limit (e.g. 1M, 100K)")
        net_group.add(self.limit_rate)
        
        self.concurrent_fragments = Adw.SpinRow.new_with_range(0, 16, 1)
        self.concurrent_fragments.set_title("Concurrent fragments")
        self.concurrent_fragments.set_value(0)
        net_group.add(self.concurrent_fragments)
        
        self.impersonate = Adw.EntryRow(title="Impersonate browser (e.g. chrome-110)")
        net_group.add(self.impersonate)
        
        # Advanced flags
        flag_group = Adw.PreferencesGroup(title="Advanced")
        main_box.append(flag_group)
        
        self.extra_flags = Adw.EntryRow(title="Extra yt-dlp flags")
        flag_group.add(self.extra_flags)
        
        # Format selection (with fetch button)
        format_group = Adw.PreferencesGroup(title="Formats")
        main_box.append(format_group)
        
        format_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.format_combo = Gtk.DropDown.new_from_strings(["Select a format..."])
        # Disabled until formats are fetched
        self.format_combo.set_sensitive(False)
        format_row.append(self.format_combo)
        self.btn_fetch = Gtk.Button(label="Fetch formats")
        format_row.append(self.btn_fetch)
        # Inline spinner + status for fetch
        self._fmt_spinner = Gtk.Spinner()
        self._fmt_spinner.set_visible(False)
        format_row.append(self._fmt_spinner)
        self._fmt_status = Gtk.Label(label="", xalign=0.0)
        self._fmt_status.add_css_class("dim-label")
        format_row.append(self._fmt_status)
        format_action = Adw.ActionRow()
        format_action.set_title("Available formats")
        format_action.set_child(format_row)
        format_group.add(format_action)
        
        # When user selects a specific format, force Quality to "Custom" for clarity
        self.format_combo.connect("notify::selected", self._on_format_selected)
        
        # Target directory
        dir_group = Adw.PreferencesGroup(title="Destination")
        main_box.append(dir_group)
        
        self.target_dir = Adw.EntryRow(title="Download directory")
        self.target_dir.set_text(str(Path.home() / "Downloads"))
        dir_group.add(self.target_dir)
        
        # Connect quality mode change to show/hide custom format
        self.quality_mode.connect("notify::selected", self._on_quality_mode_changed)
        
        # Buttons
        btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_cancel = Gtk.Button(label="Cancel")
        btn_cancel.connect("clicked", lambda *_: self.destroy())
        btn_download = Gtk.Button(label="Download", css_classes=["suggested-action"])
        btn_download.connect("clicked", self._on_download)
        btns.append(btn_cancel)
        btns.append(btn_download)
        main_box.append(btns)
        
        root.set_content(main_box)
        
        # Internal state
        self._accepted = False
        self._selected_format_id = None
        self._format_map: dict[str, str] = {}
        # Wire cookies sensitivity
        self._wire_cookies_sensitive()

        # End of constructor

    def _on_quality_mode_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        is_custom = combo.get_selected() == 2  # "Custom" option
        self.custom_format_row.set_visible(is_custom)

    def _on_format_selected(self, drop: Gtk.DropDown, _pspec) -> None:
        if drop.get_selected() > 0:
            # Switch UI to "Custom" and reveal the custom format row for transparency
            self.quality_mode.set_selected(2)
            self.custom_format_row.set_visible(True)

    def _on_download(self, _btn) -> None:
        self._accepted = True
        self.destroy()

    # --- Formats fetch UX helpers ---
    def begin_format_fetch(self) -> None:
        try:
            self.btn_fetch.set_sensitive(False)
        except Exception:
            pass
        self._fmt_status.set_text("Fetching formats…")
        self._fmt_spinner.set_visible(True)
        try:
            self._fmt_spinner.start()
        except Exception:
            pass

    def _end_format_fetch(self) -> None:
        try:
            self._fmt_spinner.stop()
        except Exception:
            pass
        self._fmt_spinner.set_visible(False)
        self._fmt_status.set_text("")
        try:
            self.btn_fetch.set_sensitive(True)
        except Exception:
            pass

    # --- Cookies enable/disable wiring ---
    def _wire_cookies_sensitive(self) -> None:
        def _apply_sensitive() -> None:
            on = self.use_cookies.get_active()
            self.cookies_browser.set_sensitive(on)
            self.cookies_keyring.set_sensitive(on)
            self.cookies_profile.set_sensitive(on)
            self.cookies_container.set_sensitive(on)

        # Initialize and connect
        _apply_sensitive()
        try:
            self.use_cookies.connect("notify::active", lambda *_: _apply_sensitive())
        except Exception:
            pass

    def get_options(self) -> tuple[bool, DownloadOptions]:
        """Returns (accepted, options)"""
        if not self._accepted:
            return False, DownloadOptions()
        
        # Get the selected format if available
        format_idx = self.format_combo.get_selected()
        format_id: str | None = None
        if format_idx > 0:  # Skip the "Select a format..." option
            model = self.format_combo.get_model()
            selected_str: str | None = None
            try:
                if isinstance(model, Gtk.StringList):
                    # Gtk.StringList.get_string is the robust way to get the string
                    selected_str = model.get_string(format_idx)
            except Exception:
                selected_str = None
            if selected_str:
                format_id = self._format_map.get(selected_str)
        
        # Get custom format or selected format
        custom_format = self.custom_format_row.get_text().strip() if self.custom_format_row.get_visible() else None
        if not custom_format and format_id:
            custom_format = str(format_id)
        # If a specific format was chosen from the list, treat it as "Custom" quality
        quality_idx = int(self.quality_mode.get_selected())
        if format_id and quality_idx != 2:
            quality_idx = 2
        
        # Target dir
        td = self.target_dir.get_text().strip()
        target_dir = Path(td) if td else None

        opts = DownloadOptions(
            quality_mode=["highest", "lowest", "custom"][quality_idx],
            custom_format=custom_format,
            sort_string=self.sort_string_row.get_text().strip(),
            write_subs=self.write_subs.get_active(),
            subs_langs=self.subs_langs.get_text().strip(),
            write_auto_subs=self.write_auto_subs.get_active(),
            subs_format=["vtt", "srt", "best"][int(self.subs_format_row.get_selected())],
            sb_mark=self.sb_mark_row.get_text().strip(),
            sb_remove=self.sb_remove_row.get_text().strip(),
            embed_metadata=self.embed_metadata.get_active(),
            embed_thumbnail=self.embed_thumbnail.get_active(),
            write_thumbnail=self.write_thumbnail.get_active(),
            use_cookies=self.use_cookies.get_active(),
            cookies_browser=["firefox", "chromium", "brave", "edge"][int(self.cookies_browser.get_selected())],
            cookies_keyring=self.cookies_keyring.get_text().strip(),
            cookies_profile=self.cookies_profile.get_text().strip(),
            cookies_container=self.cookies_container.get_text().strip(),
            limit_rate=self.limit_rate.get_text().strip(),
            concurrent_fragments=int(self.concurrent_fragments.get_value()),
            impersonate=self.impersonate.get_text().strip(),
            extra_flags=self.extra_flags.get_text().strip(),
            target_dir=target_dir,
        )
        return True, opts

    def set_formats(self, formats: list[tuple[str, str]]) -> None:
        """Update the format dropdown with available formats."""
        # Always end fetch UI state on return to main loop
        self._end_format_fetch()
        if not formats:
            # Keep dropdown disabled if nothing available
            self.format_combo.set_sensitive(False)
            # Reset model just in case
            self.format_combo.set_model(Gtk.StringList.new(["Select a format..."]))
            return

        # Create new model with "Select a format..." as first option
        strings = ["Select a format..."] + [f"{fmt_id}: {fmt_label}" for fmt_id, fmt_label in formats]
        model = Gtk.StringList.new(strings)
        self.format_combo.set_model(model)
        # Enable dropdown now that we have content
        self.format_combo.set_sensitive(True)

        # Store the mapping
        self._format_map = {f"{fmt_id}: {fmt_label}": fmt_id for fmt_id, fmt_label in formats}

class PreferencesWindow(Adw.PreferencesWindow):
    def __init__(self, parent: Gtk.Window, settings: dict) -> None:
        super().__init__(transient_for=parent, modal=True, title="Preferences")
        self.settings = settings
        self.set_search_enabled(False)

        # Playback page
        page_play = Adw.PreferencesPage(title="Playback")
        group_play = Adw.PreferencesGroup(title="Player")
        page_play.add(group_play)

        # Provider page
        page_provider = Adw.PreferencesPage(title="Provider")

        # Auto-hide MPV controls
        self.autohide_controls = Adw.SwitchRow(
            title="Auto-hide MPV controls outside Player view"
        )
        self.autohide_controls.set_active(bool(settings.get("mpv_autohide_controls", False)))
        group_play.add(self.autohide_controls)

        # Playback mode
        self.playback_mode = Adw.ComboRow(
            title="Default playback mode",
            model=Gtk.StringList.new([
                "External MPV (separate window)",
                "In-window (X11) / Integrated (Wayland)"
            ]),
        )
        mode_val = settings.get("playback_mode", "external")
        self.playback_mode.set_selected(0 if mode_val == "external" else 1)
        group_play.add(self.playback_mode)

        # Playback quality
        self.playback_quality = Adw.ComboRow(
            title="Preferred playback quality",
            model=Gtk.StringList.new(["Auto (best)", "2160p", "1440p", "1080p", "720p", "480p"]),
        )
        quality_val = settings.get("mpv_quality", "auto")
        quality_idx = {"auto": 0, "2160": 1, "1440": 2, "1080": 3, "720": 4, "480": 5}.get(
            quality_val, 0
        )
        self.playback_quality.set_selected(quality_idx)
        group_play.add(self.playback_quality)

        # Extra MPV args
        self.mpv_args = Adw.EntryRow(title="MPV extra args")
        self.mpv_args.set_text(settings.get("mpv_args", ""))
        group_play.add(self.mpv_args)

        # Cookies group for MPV
        cookies_group = Adw.PreferencesGroup(title="MPV cookies (optional)")
        page_play.add(cookies_group)

        self.cookies_enable = Adw.SwitchRow(title="Pass browser cookies to MPV")
        self.cookies_enable.set_active(bool(settings.get("mpv_cookies_enable", False)))
        cookies_group.add(self.cookies_enable)

        self.cmb_browser = Adw.ComboRow(
            title="Browser",
            model=Gtk.StringList.new(["", "firefox", "chromium", "brave", "edge"]),
        )
        browser = (settings.get("mpv_cookies_browser") or "").strip()
        try:
            self.cmb_browser.set_selected(["", "firefox", "chromium", "brave", "edge"].index(browser))
        except ValueError:
            self.cmb_browser.set_selected(0)
        cookies_group.add(self.cmb_browser)

        self.entry_keyring = Adw.EntryRow(title="Keyring (optional)")
        self.entry_keyring.set_text(settings.get("mpv_cookies_keyring", ""))
        cookies_group.add(self.entry_keyring)

        self.entry_profile = Adw.EntryRow(title="Profile (optional)")
        self.entry_profile.set_text(settings.get("mpv_cookies_profile", ""))
        cookies_group.add(self.entry_profile)

        self.entry_container = Adw.EntryRow(title="Container (Firefox; optional)")
        self.entry_container.set_text(settings.get("mpv_cookies_container", ""))
        cookies_group.add(self.entry_container)

        # Provider group (Invidious)
        group_provider = Adw.PreferencesGroup(title="Invidious")
        page_provider.add(group_provider)
        self.use_invidious = Adw.SwitchRow(title="Use Invidious backend for search/channel")
        self.use_invidious.set_active(bool(settings.get("use_invidious", False)))
        group_provider.add(self.use_invidious)

        self.entry_invidious = Adw.EntryRow(title="Invidious instance")
        self.entry_invidious.set_text(settings.get("invidious_instance", "https://yewtu.be"))
        group_provider.add(self.entry_invidious)

        # Downloads page
        page_dl = Adw.PreferencesPage(title="Downloads")
        group_dl = Adw.PreferencesGroup(title="Location")
        page_dl.add(group_dl)

        self.download_button = Adw.ActionRow(title="Download directory")
        self._download_dir_label = Gtk.Label(label=settings.get("download_dir", ""), xalign=1.0)
        self.download_button.add_suffix(self._download_dir_label)
        self.download_button.set_activatable(True)
        self.download_button.connect("activated", self._choose_dir)
        group_dl.add(self.download_button)

        # After completion
        group_after = Adw.PreferencesGroup(title="After completion")
        page_dl.add(group_after)
        self.sw_auto_open = Adw.SwitchRow(title="Open download folder when a download finishes")
        self.sw_auto_open.set_active(bool(settings.get("download_auto_open_folder", False)))
        group_after.add(self.sw_auto_open)

        # Filename template
        self.entry_template = Adw.EntryRow(title="Filename template")
        self.entry_template.set_text(settings.get("download_template", "%(title)s.%(ext)s"))
        self.entry_template.set_tooltip_text("yt-dlp template, e.g. %(title)s.%(ext)s or %(uploader)s/%(title)s.%(ext)s")
        group_dl.add(self.entry_template)

        # Network (global)
        group_net = Adw.PreferencesGroup(title="Network")
        page_dl.add(group_net)
        self.entry_proxy = Adw.EntryRow(title="HTTP(S) proxy (optional)")
        self.entry_proxy.set_text(settings.get("http_proxy", ""))
        group_net.add(self.entry_proxy)

        # Queue / concurrency
        group_queue = Adw.PreferencesGroup(title="Queue")
        page_dl.add(group_queue)
        self.spin_concurrent = Adw.SpinRow.new_with_range(1, 8, 1)
        self.spin_concurrent.set_title("Max concurrent downloads")
        try:
            self.spin_concurrent.set_value(float(int(settings.get("max_concurrent_downloads", 3) or 3)))
        except Exception:
            self.spin_concurrent.set_value(3.0)
        group_queue.add(self.spin_concurrent)

        self.add(page_play)
        self.add(page_provider)
        self.add(page_dl)

        self.connect("close-request", self._on_close)

    def _choose_dir(self, *_a) -> None:
        dlg = Gtk.FileDialog(title="Choose download folder")
        dlg.set_modal(True)
        dlg.select_folder(self, None, self._on_folder_chosen, None)

    def _on_folder_chosen(self, dialog: Gtk.FileDialog, res: Gio.AsyncResult, _data) -> None:
        try:
            f = dialog.select_folder_finish(res)
        except Exception:
            return
        path = f.get_path() or ""
        self._download_dir_label.set_text(path)

    def _on_close(self, *_a) -> bool:
        sel = self.playback_mode.get_selected()
        self.settings["playback_mode"] = "external" if sel == 0 else "embedded"
        self.settings["mpv_args"] = self.mpv_args.get_text()
        self.settings["download_dir"] = self._download_dir_label.get_text()

        qsel = self.playback_quality.get_selected()
        qmap = {0: "auto", 1: "2160", 2: "1440", 3: "1080", 4: "720", 5: "480"}
        self.settings["mpv_quality"] = qmap.get(qsel, "auto")

        self.settings["mpv_cookies_enable"] = self.cookies_enable.get_active()
        browsers = ["", "firefox", "chromium", "brave", "edge"]
        bsel = self.cmb_browser.get_selected()
        self.settings["mpv_cookies_browser"] = browsers[bsel] if 0 <= bsel < len(browsers) else ""
        self.settings["mpv_cookies_keyring"] = self.entry_keyring.get_text()
        self.settings["mpv_cookies_profile"] = self.entry_profile.get_text()
        self.settings["mpv_cookies_container"] = self.entry_container.get_text()
        # Global proxy
        self.settings["http_proxy"] = self.entry_proxy.get_text()
        # Concurrency
        self.settings["max_concurrent_downloads"] = int(self.spin_concurrent.get_value())
        # Provider settings
        self.settings["use_invidious"] = bool(self.use_invidious.get_active())
        self.settings["invidious_instance"] = self.entry_invidious.get_text().strip() or "https://yewtu.be"
        # Auto-hide MPV controls
        self.settings["mpv_autohide_controls"] = bool(self.autohide_controls.get_active())
        # After completion + template
        self.settings["download_auto_open_folder"] = bool(self.sw_auto_open.get_active())
        self.settings["download_template"] = self.entry_template.get_text().strip() or "%(title)s.%(ext)s"
        return False