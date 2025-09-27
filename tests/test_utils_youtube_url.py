from whirltube.util import is_valid_youtube_url


def test_is_valid_youtube_url_basic_youtube():
    assert is_valid_youtube_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert is_valid_youtube_url("http://youtube.com/shorts/abc")
    assert is_valid_youtube_url("https://youtu.be/dQw4w9WgXcQ")


def test_is_valid_youtube_url_rejects_non_http():
    assert not is_valid_youtube_url("ftp://youtube.com/video")
    assert not is_valid_youtube_url("file:///tmp/thing")
    assert not is_valid_youtube_url("not a url")
    assert not is_valid_youtube_url("")
    assert not is_valid_youtube_url(None)  # type: ignore[arg-type]


def test_is_valid_youtube_url_allows_invidious_host():
    assert not is_valid_youtube_url("https://yewtu.be/watch?v=foo")
    assert is_valid_youtube_url("https://yewtu.be/watch?v=foo", allowed_hosts=["yewtu.be"])


def test_is_valid_youtube_url_rejects_unknown_host():
    assert not is_valid_youtube_url("https://example.com/watch?v=foo")
    assert not is_valid_youtube_url("https://ex.youtube.evil.example/watch?v=foo")
    assert not is_valid_youtube_url("https://you.tube.com/watch?v=foo")