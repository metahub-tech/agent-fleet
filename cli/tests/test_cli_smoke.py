import pytest
from fleet.cli import main, _network_choices
from fleet.detect import TailscaleStatus


@pytest.mark.parametrize("ts", [
    None,
    TailscaleStatus(hostname="laptop", fqdn="laptop.tail-net.ts.net"),
])
def test_network_choices_default_always_in_titles(ts):
    """Regression: default title must match one of the Choice titles.
    questionary.select raises ValueError at construction if not. Tag v0.5.0-alpha
    shipped with a mismatch ("Tailscale (recommended)" vs actual title
    "Tailscale (recommended) [logged in]") that crashed the wizard before the
    second prompt could render."""
    choices, default = _network_choices(ts)
    titles = [c.title for c in choices]
    assert default in titles, f"default {default!r} not in {titles!r}"


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
