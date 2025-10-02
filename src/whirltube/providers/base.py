from __future__ import annotations

from typing import Protocol, TYPE_CHECKING, Tuple

if TYPE_CHECKING:
    from ..models import Video, Format

class Provider(Protocol):
    """
    Protocol defining the interface for all data providers (e.g., yt-dlp, Invidious, InnerTube).
    """
    def search(self, query: str, limit: int, filters: dict[str, str] | None = None) -> list[Video]:
        ...

    def trending(self) -> list[Video]:
        ...

    def related(self, video_id: str) -> list[Video]:
        ...

    def comments(self, video_id: str) -> list[Video]:
        ...

    def channel_tab(self, channel_url: str, tab: str) -> list[Video]:
        ...

    def fetch_formats(self, url: str) -> list[tuple[str, str]]:
        ...

    def get_video_info(self, url: str) -> Video | None:
        ...

    def set_cookies_from_browser(self, spec: str) -> None:
        """Set cookies for the provider from a browser specification string."""
        ...

    def suggestions(self, query: str, max_items: int = 10) -> list[str]:
        """Get search suggestions/autocomplete."""
        ...

    def get_proxy(self) -> str | None:
        """Get the configured proxy string."""
        ...
