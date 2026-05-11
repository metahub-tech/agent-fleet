import pytest
from fleet.cli import main


def test_cli_no_args_prints_help(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "agent-fleet" in captured.out.lower() or "setup" in captured.out.lower()


def test_cli_version_flag(capsys):
    import fleet
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    # argparse --version writes to stdout AND exits; the version should appear in stdout
    assert fleet.__version__ in captured.out
