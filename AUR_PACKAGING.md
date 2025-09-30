# AUR Packaging for WhirlTube

This document explains how to publish WhirlTube to the Arch User Repository (AUR).

## Package Overview

Two packages are provided:
- `whirltube` - Stable releases from GitHub tags
- `whirltube-git` - Git development version

## Dependencies

### Runtime Dependencies
- `python` - Core Python runtime
- `gtk4` - GTK 4.x libraries
- `libadwaita` - GNOME's Adwaita widget library
- `python-gobject` - Python GObject bindings
- `yt-dlp` - Video download/playback backend
- `python-httpx` - HTTP client library
- `mpv` - Video player

### Optional Dependencies
- `python-mpv` - In-window (embedded) playback on X11
- `libnotify` - Desktop notifications
- `python-pillow` - Thumbnail WebP fallback decoding

### Build Dependencies
- `python-build` - Python build frontend
- `python-installer` - Python wheel installer
- `python-hatchling` - Build backend
- `git` - For Git package

## Publishing Instructions

### 1. Create AUR Account
- Visit https://aur.archlinux.org
- Sign up/log in
- Add your SSH public key under Account → SSH Public Key

### 2. Publish Stable Package (whirltube)

```bash
cd whirltube
# Initialize git repository
git init
git add PKGBUILD .SRCINFO

# Create initial commit
git commit -m "Initial commit"

# Add AUR remote and push
git remote add aur ssh://aur@aur.archlinux.org/whirltube.git
git push -u aur HEAD:master
```

### 3. Publish Git Package (whirltube-git)

```bash
cd whirltube-git
# Initialize git repository
git init
git add PKGBUILD .SRCINFO

# Create initial commit
git commit -m "Initial commit"

# Add AUR remote and push
git remote add aur ssh://aur@aur.archlinux.org/whirltube-git.git
git push -u aur HEAD:master
```

## Maintaining Packages

### Stable Package Updates
1. Tag a new release on GitHub (e.g., v0.5.0)
2. Update `pkgver` in the PKGBUILD
3. Update `sha256sums` with the new tarball checksum
4. Run `makepkg --printsrcinfo > .SRCINFO`
5. Commit and push to AUR

### Git Package Updates
- No version updates needed - the `pkgver()` function automatically calculates version at build time
- Only update if build dependencies change

## Verification

You can test the packages locally before publishing:

```bash
# Test building (do not install)
makepkg -d

# Test building and install
makepkg -si
```

## Notes

- The packages include desktop entry and icons
- The `provides=('whirltube')` in both packages prevents conflicts when switching between versions
- The `conflicts` field ensures only one version can be installed at a time
- Icons are installed to the standard hicolor theme paths