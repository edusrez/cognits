"""Tests for the main.py split: import graph sanity."""


def test_import_bootstrap():
    from cognits import bootstrap
    assert bootstrap._Server is not None
    assert bootstrap._setup_file_logging is not None


def test_import_tui():
    from cognits import tui
    assert tui.CognitsTUI is not None


def test_import_cli():
    from cognits import cli
    assert cli.main is not None


def test_main_re_exports_from_cli():
    from cognits import main
    from cognits import cli
    assert main.main is cli.main


def test_import_cognits_version():
    import cognits
    assert isinstance(cognits.__version__, str)
    assert len(cognits.__version__) > 0
