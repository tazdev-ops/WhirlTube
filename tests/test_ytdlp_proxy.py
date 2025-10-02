from __future__ import annotations
import pytest
from src.whirltube.providers.ytdlp import YTDLPProvider


def test_proxy_persists_after_set_cookies():
    \"\"\"Ensure proxy is retained when applying cookies-from-browser.\"\"\"
    provider = YTDLPProvider(proxy=\"http://127.0.0.1:8080\")
    
    # Verify proxy is set initially
    assert provider._opts_base.get(\"proxy\") == \"http://127.0.0.1:8080\"
    
    # Apply cookies
    provider.set_cookies_from_browser(\"firefox+gnomekeyring:default::Work\")
    
    # Proxy should still be present
    assert provider._opts_base.get(\"proxy\") == \"http://127.0.0.1:8080\"
    assert provider._opts_base.get(\"cookiesfrombrowser\") is not None


def test_proxy_persists_on_invalid_cookies():
    \"\"\"Ensure proxy is retained even when cookie spec is invalid.\"\"\"
    provider = YTDLPProvider(proxy=\"http://127.0.0.1:8080\")
    
    # Try invalid cookie spec
    provider.set_cookies_from_browser(\"::::invalid:::\")
    
    # Proxy should still be there
    assert provider._opts_base.get(\"proxy\") == \"http://127.0.0.1:8080\"