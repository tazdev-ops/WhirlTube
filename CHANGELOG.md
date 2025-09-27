# Changelog
All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog and adheres to Semantic Versioning.

## [0.4.2] - 2025-09-27
### Added
- Unified download progress across main UI and Quick Download (YtDlpRunner JSON).
- Loading indicators for searches and browsing.
- Thumbnail failure fallback to avoid blank image boxes.
- Back navigation controller (NavigationController).
- DownloadManager centralizes downloads and progress rows.
- Doctor script and real import checks in deep_verify (local mode).

### Fixed
- Download dialog “Available formats” reliably honors selected format_id; auto-switches to “Custom”.
- Preferences “Download directory” applies immediately without restart.
- About dialog shows correct version (0.4.2).
- Desktop entry Name fixed (“WhirlTube”).

### Changed
- README updated; removed “Trending” from docs.

[0.4.2]: https://github.com/mativiters/WhirlTube/releases/tag/v0.4.2
