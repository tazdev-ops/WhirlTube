from __future__ import annotations
import pytest
from unittest.mock import patch, MagicMock
from src.whirltube.services.native_resolver import get_ios_hls
from src.whirltube.util import safe_httpx_proxy


def test_native_resolver_uses_proxy():
    \"\"\"Ensure native iOS HLS resolver passes proxy to httpx.\"\"\"
    with patch(\"httpx.Client\") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {\"streamingData\": {\"hlsManifestUrl\": \"https://example.com/hls.m3u8\"}}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
        
        proxy = \"http://127.0.0.1:8080\"
        result = get_ios_hls(\"test_id\", proxy=proxy)
        
        # Verify Client was called with proxies
        mock_client.assert_called_once_with(proxies={\"all://\": safe_httpx_proxy(proxy)}, timeout=8.0)
        assert result == \"https://example.com/hls.m3u8\"


def test_native_resolver_no_proxy():
    \"\"\"Ensure resolver works without proxy.\"\"\"
    with patch(\"httpx.Client\") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {\"streamingData\": {\"hlsManifestUrl\": \"https://example.com/hls.m3u8\"}}
        mock_client.return_value.__enter__.return_value.post.return_value = mock_resp
        
        result = get_ios_hls(\"test_id\", proxy=None)
        
        mock_client.assert_called_once_with(proxies=None, timeout=8.0)
        assert result == \"https://example.com/hls.m3u8\"