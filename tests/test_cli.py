import pytest

from evalops_kit import __version__
from evalops_kit.cli import main


def test_package_import_has_version() -> None:
    assert __version__


def test_cli_help_shows_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "evalops-kit" in output
    assert "run" in output
    assert "diff" in output


@pytest.mark.parametrize("subcommand", ["run", "diff"])
def test_subcommand_help(subcommand: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([subcommand, "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert subcommand in output
