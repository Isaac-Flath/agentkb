"""Smoke tests for the communications CLI group."""

from click.testing import CliRunner

from agentkb.communications.cli import communications


def test_communications_help_lists_commands():
    runner = CliRunner()
    result = runner.invoke(communications, ["--help"])
    assert result.exit_code == 0
    for cmd in ("fetch", "index", "list", "show", "status", "x"):
        assert cmd in result.output


def test_x_help_lists_subcommands():
    runner = CliRunner()
    result = runner.invoke(communications, ["x", "--help"])
    assert result.exit_code == 0
    for sub in ("add-handle", "remove-handle", "list-handles", "fetch"):
        assert sub in result.output


def test_x_list_handles_empty(tmp_path, monkeypatch):
    """With no handles registered, list-handles prints a hint."""
    monkeypatch.setenv("HOME", str(tmp_path))
    # Force a fresh Settings() read
    monkeypatch.delenv("AGENTKB_COMMUNICATIONS_PATH", raising=False)

    runner = CliRunner()
    result = runner.invoke(communications, ["x", "list-handles"])
    assert result.exit_code == 0
    assert "No X handles tracked" in result.output


def test_status_with_no_data(tmp_path, monkeypatch):
    """Status runs cleanly on a fresh install."""
    monkeypatch.setenv("HOME", str(tmp_path))
    runner = CliRunner()
    result = runner.invoke(communications, ["status"])
    assert result.exit_code == 0


def test_add_handle_without_token_errors(tmp_path, monkeypatch):
    """Without X_BEARER_TOKEN, add-handle errors cleanly rather than crashing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)

    runner = CliRunner()
    result = runner.invoke(communications, ["x", "add-handle", "nonexistent-handle-xyz-foo"])
    # Command itself exits 0 but prints the error to stderr.
    assert "X_BEARER_TOKEN is not set" in (result.output + (result.stderr if result.stderr_bytes else ""))


def test_x_fetch_single_handle_without_token_errors(tmp_path, monkeypatch):
    """`x fetch --handle X` must not crash with a traceback when the token is missing.

    It raises RuntimeError deep in the fetch path; the CLI wraps it as
    click.ClickException so the user sees `Error: ...` with exit code 1.
    Regression test — before the fix this bubbled a full Python traceback.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("X_BEARER_TOKEN", raising=False)

    # Seed a manifest so we hit the API path rather than the "handle not registered"
    # branch (which would error first for a different reason).
    x_raw = tmp_path / ".agentkb" / "communications" / "raw" / "x"
    x_raw.mkdir(parents=True)
    (x_raw / "_handles.json").write_text('{"handles": {"karpathy": {"user_id": "33836629"}}}')

    runner = CliRunner()
    result = runner.invoke(communications, ["x", "fetch", "--handle", "karpathy"])
    assert result.exit_code != 0
    assert "X_BEARER_TOKEN is not set" in result.output
    # Crucially, no traceback in the output
    assert "Traceback" not in result.output
