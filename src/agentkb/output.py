"""Shared terminal output helpers."""

import click


def echo_status(message: str, *, json_output: bool = False) -> None:
    """Emit status without corrupting machine-readable JSON output."""
    click.echo(message, err=json_output)
