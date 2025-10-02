from __future__ import annotations

import pytest
from src.whirltube.providers.ytdlp import YTDLPProvider

@pytest.fixture
def ytdlp_provider_with_proxy():
    """Fixture for YTDLPProvider initialized with a proxy."""
    return YTDLPProvider(proxy="http://test-proxy:8080")

def test_ytdlp_proxy_retention_after_cookies(ytdlp_provider_with_proxy):
    """
    Test that the proxy setting is retained after calling set_cookies_from_browser.
    (Task 1 Acceptance Test)
    """
    provider = ytdlp_provider_with_proxy
    
    # 1. Assert proxy is initially set
    assert provider._opts_base.get("proxy") == "http://test-proxy:8080"
    
    # 2. Call set_cookies_from_browser (even with a dummy spec)
    provider.set_cookies_from_browser("firefox:default")
    
    # 3. Assert proxy is still set in the base options
    assert provider._opts_base.get("proxy") == "http://test-proxy:8080"
    
    # 4. Assert cookies are also set
    assert "cookiesfrombrowser" in provider._opts_base
    
    # 5. Call set_cookies_from_browser with None (to clear cookies)
    provider.set_cookies_from_browser(None)
    
    # 6. Assert proxy is still set, but cookies are gone
    assert provider._opts_base.get("proxy") == "http://test-proxy:8080"
    assert "cookiesfrombrowser" not in provider._opts_base
