import pytest
from fleet.cli import main, _network_choices
from fleet.detect import TailscaleStatus


@pytest.mark.parametrize("ts", [
    None,
    TailscaleStatus(hostname="laptop", fqdn="laptop.tail-net.ts.net"),
])
def test_network_choices_default_always_in_values(ts):
    """Regression: default must be one of the Choice values.

    questionary.select validates `default` against Choice.value (NOT Choice.title)
    — see questionary/prompts/common.py:30-31:

        if default is not None and default not in choices and default not in choices_values:
            raise ValueError(...)

    v0.5.0-alpha shipped with a hardcoded title-string default, which is neither
    a Choice object nor a value, so the wizard crashed at the second prompt.
    The first attempted fix (#7) regressed in a different direction (used
    Choice.title) — same class of bug.  This test catches BOTH forms by checking
    against values, the same predicate questionary uses internally."""
    choices, default = _network_choices(ts)
    values = [c.value for c in choices]
    assert default in values, f"default {default!r} not in values {values!r}"
    # Also functionally exercise the constructor so we'd catch any future
    # validation rule change in questionary itself.
    import questionary
    questionary.select("test", choices=choices, default=default)


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
