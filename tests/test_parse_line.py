from whirltube.ytdlp_runner import parse_line, PREFIX
from typing import Any

# Define a simple Event class for testing purposes, as it's not imported in the test file
class Event:
    def __init__(self, kind: str, payload: Any):
        self.kind = kind
        self.payload = payload

def test_parse_line_progress_event_basic():
    line = f'{PREFIX}{{"type":"downloading","eta":12,"downloaded_bytes":1024,"total_bytes":2048}}'
    evs = parse_line(line)
    assert isinstance(evs, list)
    # The actual parse_line returns a list of DownloadProgress objects, which have 'kind' and 'payload' attributes.
    # Assuming the structure of the returned object is compatible for this test.
    assert evs and evs[0].kind == "downloading"
    payload = evs[0].payload
    assert payload["eta"] == 12
    assert payload["downloaded_bytes"] == 1024
    assert payload["total_bytes"] == 2048


def test_parse_line_non_prefixed_is_none():
    assert parse_line("some random output") is None


def test_parse_line_error_std_and_plain():
    e1 = parse_line("stderr:ERROR: boom")
    assert isinstance(e1, Exception)
    assert "boom" in str(e1)
    e2 = parse_line("ERROR: boom2")
    assert isinstance(e2, Exception)
    assert "boom2" in str(e2)


def test_parse_line_NA_becomes_null():
    line = f'{PREFIX}{{"type":"downloading","eta":NA,"speed":NA}}'
    evs = parse_line(line)
    assert isinstance(evs, list) and evs[0].payload["eta"] is None and evs[0].payload["speed"] is None
