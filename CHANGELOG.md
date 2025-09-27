# Changelog

All notable changes to this project will be documented in this file.

## 0.4.5
- Downloads:
  - Cleaner UI: actions moved into an "Actions" popover menu (Cancel, Retry, Remove, Open/Show in folder).
  - Configurable filename template (Preferences → Downloads).
  - Queue, Cancel All, Clear Finished, Retry/Remove rows (from previous batches).
  - In-app toasts and desktop notifications on finish/error (from previous batches).
- Player:
  - "Auto-hide MPV controls outside Player view" setting (Preferences → Playback).
  - MPV hotkeys (J/K/L, +/- , X) and Copy URL @ time (T) (from previous batches).
- Provider:
  - Invidious toggle and instance (Preferences → Provider) (from previous batches).
- Packaging:
  - Desktop file, AppStream metainfo, Flatpak scaffold (from previous batches).
- Internal:
  - Safer proxy handling and test coverage.
  - Lazy GI imports for testability.

## 0.4.4
- Downloads:
  - Retry/Remove per row, Cancel All and Clear Finished menu items.
- Provider:
  - Wire Subscriptions menu actions.

## 0.4.3
- Downloads:
  - Queue with configurable max concurrency.
  - "Open in Browser", "Copy URL", "Copy Title".
- Misc: URL validation and alignment fixes.

## 0.4.2
- Initial public release series baseline.