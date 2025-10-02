"""Quick quality download presets."""
from __future__ import annotations

from pathlib import Path

from .dialogs import DownloadOptions


# Preset configurations
QUALITY_PRESETS = {
    "2160p": {
        "label": "4K",
        "tooltip": "Download in 4K (2160p)",
        "format": "bv*[height<=2160]+ba/b[height<=2160]",
        "sort": "res:2160",
    },
    "1440p": {
        "label": "2K",
        "tooltip": "Download in 2K (1440p)",
        "format": "bv*[height<=1440]+ba/b[height<=1440]",
        "sort": "res:1440",
    },
    "1080p": {
        "label": "1080p",
        "tooltip": "Download in Full HD (1080p)",
        "format": "bv*[height<=1080]+ba/b[height<=1080]",
        "sort": "res:1080",
    },
    "720p": {
        "label": "720p",
        "tooltip": "Download in HD (720p)",
        "format": "bv*[height<=720]+ba/b[height<=720]",
        "sort": "res:720",
    },
    "480p": {
        "label": "480p",
        "tooltip": "Download in SD (480p)",
        "format": "bv*[height<=480]+ba/b[height<=480]",
        "sort": "res:480",
    },
    "audio": {
        "label": "🎵 Audio",
        "tooltip": "Download audio only (best quality)",
        "format": "ba/b",
        "audio_only": True,
    },
}


def get_quick_quality_options(quality_key: str, target_dir: Path | None = None) -> DownloadOptions:
    """
    Get DownloadOptions for a quality preset.
    
    Args:
        quality_key: One of "2160p", "1440p", "1080p", "720p", "480p", "audio"
        target_dir: Optional target directory override
        
    Returns:
        DownloadOptions configured for the preset
    """
    preset = QUALITY_PRESETS.get(quality_key)
    if not preset:
        # Default to 1080p if invalid key
        preset = QUALITY_PRESETS["1080p"]
    
    opts = DownloadOptions(
        quality_mode="custom",
        custom_format=preset["format"],
        sort_string=preset.get("sort", ""),
        target_dir=target_dir,
    )
    
    # For audio-only, add extraction flags
    if preset.get("audio_only"):
        opts.extra_flags = "-x --audio-format mp3 --audio-quality 0"
    
    return opts


def get_enabled_presets(setting_value: str | None = None) -> list[str]:
    """
    Get list of enabled quality presets.
    
    Args:
        setting_value: Comma-separated preset keys, or None for defaults
        
    Returns:
        List of preset keys in order
    """
    if setting_value:
        # Parse user setting
        presets = [p.strip() for p in setting_value.split(",") if p.strip()]
        # Validate all presets exist
        return [p for p in presets if p in QUALITY_PRESETS]
    
    # Default presets
    return ["1080p", "720p", "audio"]


def get_preset_label(quality_key: str) -> str:
    """Get display label for preset"""
    return QUALITY_PRESETS.get(quality_key, {}).get("label", quality_key)


def get_preset_tooltip(quality_key: str) -> str:
    """Get tooltip for preset"""
    return QUALITY_PRESETS.get(quality_key, {}).get("tooltip", f"Download in {quality_key}")