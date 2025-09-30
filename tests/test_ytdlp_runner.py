from __future__ import annotations

import pytest
import json
from src.whirltube.ytdlp_runner import parse_line, ProgressEvent, PREFIX

def test_parse_line_valid_json():
    json_data = {"type": "downloading", "progress": 0.5}
    line = f"some log line {PREFIX}{json.dumps(json_data)}"
    result = parse_line(line)
    assert isinstance(result, list)
    assert len(result) == 1
    event = result[0]
    assert event.kind == "downloading"
    assert event.payload["progress"] == 0.5

def test_parse_line_multiple_markers():
    # Should only parse the first one
    json_data = {"type": "downloading", "progress": 0.5}
    line = f"{PREFIX}{json.dumps(json_data)} {PREFIX}{{\"type\": \"ignore\"}}"
    result = parse_line(line)
    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0].kind == "downloading"

def test_parse_line_no_marker():
    line = "This is a regular log line."
    assert parse_line(line) is None

def test_parse_line_invalid_json():
    line = f"log {PREFIX} {{invalid json"
    assert parse_line(line) is None

def test_parse_line_error_stderr_prefix():
    line = "stderr:ERROR: This is a specific yt-dlp error."
    result = parse_line(line)
    assert isinstance(result, RuntimeError)
    assert str(result) == "This is a specific yt-dlp error."

def test_parse_line_error_no_prefix():
    line = "ERROR: This is a generic yt-dlp error."
    result = parse_line(line)
    assert isinstance(result, RuntimeError)
    assert str(result) == "This is a generic yt-dlp error."

def test_parse_line_error_stderr_other():
    line = "stderr:Some other error message."
    result = parse_line(line)
    assert isinstance(result, RuntimeError)
    assert str(result) == "yt-dlp error: Some other error message."

def test_parse_line_with_na_values():
    # yt-dlp sometimes outputs 'NA' for null values, which needs to be replaced
    json_data = '{"type":"downloading","eta":NA,"speed":1000}'
    line = f"log {PREFIX}{json_data}"
    result = parse_line(line)
    assert isinstance(result, list)
    assert result[0].payload["eta"] is None
    assert result[0].payload["speed"] == 1000

def test_parse_line_non_dict_json():
    line = f"log {PREFIX} [1, 2, 3]"
    assert parse_line(line) is None

def test_parse_line_missing_type():
    line = f"log {PREFIX} {{"progress": 0.5}}"
    assert parse_line(line) is None
