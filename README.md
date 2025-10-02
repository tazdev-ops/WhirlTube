# WhirlTube

**Wayland-first GTK4 YouTube client** with MPV playback and multi-provider backends.

## Status: v0.5.0 (Production-Ready)

### Highlights
- **3 Provider Backends**:
  - **YTDLPProvider** (default) — Heavy, battle-tested, complete
  - **InvidiousProvider** — Privacy-focused, API-based
  - **NewPipeProvider** (NEW) — Lightweight InnerTube, no yt-dlp dependency
- **Playback**: External MPV (default) + optional in-window embed (X11)
- **Downloads**: Unified queue system with resume/archive/collision handling
- **Quick Download**: Batch URLs, Video/Audio tabs, SponsorBlock, cookies
- **Search/Browse**: Autocomplete, trending, channels, playlists, comments
- **Persistent State**: Watch/search history, subscriptions, download queue

---

## Requirements

### System (Arch)
```bash
sudo pacman -S --needed gtk4 libadwaita python-gobject mpv ffmpeg
```

### Optional (for providers)
```bash
# YTDLPProvider (default)
pip install yt-dlp

# NewPipeProvider (lightweight)
pip install quickjs  # For signature deobfuscation
# Add your yt_extractor to PYTHONPATH or install it

# Embedded playback (X11 only)
pip install python-mpv PyOpenGL
```

---

## Install

### From Source
```bash
git clone https://github.com/yourusername/whirltube.git
cd whirltube
pip install -e .[dev]
whirltube
```

### Debug Mode
```bash
WHIRLTUBE_DEBUG=1 whirltube
tail -f ~/.cache/whirltube/whirltube.log
```

---

## Configuration

### Provider Selection
**Preferences → Provider**:
- **Use Invidious**: Toggle to switch from yt-dlp to Invidious
- **Invidious Instance**: Custom instance URL (default: `https://yewtu.be`)
- **NewPipe Mode** (TODO): Add toggle in future UI

For now, to use NewPipeProvider, edit `~/.config/whirltube/settings.json`:
```json
{
  "use_newpipe": true,
  "yt_hl": "en",
  "yt_gl": "US"
}
```

Then in `window.py`, update provider initialization:
```python
if bool(self.settings.get("use_newpipe")):
    from .providers.newpipe import NewPipeProvider
    self.provider = NewPipeProvider(
        proxy=safe_httpx_proxy(proxy_raw) if proxy_raw else None,
        hl=self.settings.get("yt_hl", "en"),
        gl=self.settings.get("yt_gl", "US")
    )
elif bool(self.settings.get("use_invidious")):
    # ... (existing Invidious logic)
else:
    # ... (existing Hybrid/YTDLP logic)
```

---

## Feature Matrix

| Feature | YTDLPProvider | InvidiousProvider | NewPipeProvider |
|---------|---------------|-------------------|-----------------|
| Search + Filters | ✅ Full | ✅ Limited | ⚠️ No filters |
| Trending | ⚠️ Flaky | ✅ Fast | ✅ Fast |
| Autocomplete | ✅ Via InnerTube | ✅ Via API | ✅ Native |
| Comments | ✅ Yes | ❌ No | ✅ Yes |
| Stream Extraction | ✅ All clients | ❌ Proxied | ✅ Multi-client |
| Signature Decipher | ✅ Built-in | N/A | ✅ QuickJS |
| Proxy Support | ✅ Yes | ✅ Yes | ✅ Yes |
| Cookies | ✅ Browser+File | ❌ No | ⚠️ Partial |
| SponsorBlock | ✅ Download+Play | ❌ No | ❌ Download only |
| External Deps | `yt-dlp` | None | `quickjs` |

---

## Roadmap (v0.6.0)

- [ ] UI toggle for NewPipeProvider
- [ ] Hybrid provider: NewPipe (search/browse) + yt-dlp (downloads)
- [ ] Native stream playback (HLS without yt-dlp)
- [ ] Flatpak packaging
- [ ] Wayland screencasting integration

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). TL;DR:
- Ruff + mypy + pytest
- Conventional commits
- Max ~300 lines/PR

---

## License

GPL-3.0-or-later
