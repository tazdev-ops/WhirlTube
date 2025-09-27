from whirltube.util import safe_httpx_proxy


def test_safe_httpx_proxy_accepts_valid_http():
    assert safe_httpx_proxy("http://127.0.0.1:8080") == "http://127.0.0.1:8080"
    assert safe_httpx_proxy("https://proxy.local:8443") == "https://proxy.local:8443"


def test_safe_httpx_proxy_accepts_valid_socks():
    assert safe_httpx_proxy("socks5://host:1080") == "socks5://host:1080"
    assert safe_httpx_proxy("socks5h://user:pass @host:1080") == "socks5h://user:pass @host:1080"


def test_safe_httpx_proxy_rejects_invalid():
    assert safe_httpx_proxy("") is None
    assert safe_httpx_proxy(None) is None
    assert safe_httpx_proxy("not a url") is None
    assert safe_httpx_proxy("file:///tmp/foo") is None
    assert safe_httpx_proxy("ftp://proxy:21") is None
    assert safe_httpx_proxy("http:///missing-host") is None