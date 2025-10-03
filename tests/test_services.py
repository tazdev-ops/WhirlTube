from unittest.mock import patch
from src.whirltube.services.native_resolver import get_ios_hls

def test_get_ios_hls_proxy_is_passed():
    """
    Test that get_ios_hls correctly passes the proxy argument to httpx.Client.
    This is a unit stub and does not perform network I/O.
    """
    test_proxy = "http://user:pass@test-proxy:8080"
    
    # Mock httpx.Client to inspect its initialization arguments
    with patch('src.whirltube.services.native_resolver.httpx.Client') as MockClient:
        # Mock the client instance's post method to avoid actual network call
        mock_client_instance = MockClient.return_value.__enter__.return_value
        mock_client_instance.post.return_value.json.return_value = {
            "streamingData": {"hlsManifestUrl": "https://hls.test/manifest.m3u8"}
        }
        
        # Call the function with a proxy
        get_ios_hls("test_id", proxy=test_proxy)
        
        # Assert httpx.Client was called once
        MockClient.assert_called_once()
        
        # Check the kwargs passed to httpx.Client
        call_kwargs = MockClient.call_args[1]
        
        # The safe_httpx_proxy function is expected to return the proxy string itself
        # when it's a simple string, which is then wrapped in {"all://": ...}
        expected_proxies = {"all://": test_proxy}
        
        assert "proxies" in call_kwargs
        assert call_kwargs["proxies"] == expected_proxies

def test_get_ios_hls_no_proxy_is_passed():
    """Test that get_ios_hls passes None for proxies when no proxy is provided."""
    with patch('src.whirltube.services.native_resolver.httpx.Client') as MockClient:
        mock_client_instance = MockClient.return_value.__enter__.return_value
        mock_client_instance.post.return_value.json.return_value = {
            "streamingData": {"hlsManifestUrl": "https://hls.test/manifest.m3u8"}
        }
        
        # Call the function without a proxy
        get_ios_hls("test_id", proxy=None)
        
        # Assert httpx.Client was called
        MockClient.assert_called_once()
        
        # Check the kwargs passed to httpx.Client
        call_kwargs = MockClient.call_args[1]
        
        # The proxies argument should be None in the call
        assert call_kwargs.get("proxies") is None