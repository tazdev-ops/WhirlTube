from whirltube.ytdlp_runner import YtDlpRunner


class _StubProc:
    def __init__(self, rc):
        self._rc = rc

    def poll(self):
        return self._rc


def test_runner_is_running_transitions():
    r = YtDlpRunner(lambda _t: None)
    assert not r.is_running()
    # Simulate running process
    r._proc = _StubProc(None)  # type: ignore[attr-defined]
    assert r.is_running()
    # Simulate finished process
    r._proc = _StubProc(0)  # type: ignore[attr-defined]
    assert not r.is_running()