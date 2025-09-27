def test_import():
    import whirltube  # noqa: F401


def test_entrypoint():
    from whirltube.app import main

    assert callable(main)
