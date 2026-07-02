#!/usr/bin/env python3
"""
CLI entrypoint for the Céges Gépjármű Magyar Közlöny Havi Riport.

Usage:
    python run.py run              # normal run (uses last_run from state DB)
    python run.py seed             # initial 30-day seed run
    python run.py init-db [--force]
    python run.py show-config
    python run.py show-state       # inspect state.db
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# Make src/ importable when run directly
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from gpjarmu_riport.config import Settings, get_settings, reload_settings  # noqa: E402
from gpjarmu_riport.state.db import StateDB  # noqa: E402
from gpjarmu_riport.utils.logging import console, setup_logging  # noqa: E402

logger = logging.getLogger(__name__)
app = typer.Typer(
    name="gpjarmu",
    help="Havi céges-gépjármű Magyar Közlöny monitor.",
    add_completion=False,
)


def _setup_logging() -> Settings:
    settings = get_settings()
    setup_logging(settings)
    return settings


def _run_pipeline_and_report(seed: bool) -> None:
    """Shared implementation for the `run` and `seed` commands."""
    settings = _setup_logging()
    try:
        settings.validate_for_run()
    except ValueError as e:
        console.print(f"[red]Configuration error:[/red] {e}")
        raise typer.Exit(1) from e

    db = StateDB(settings.state_db_path)
    from gpjarmu_riport.graph import run_pipeline

    label = "[bold green]Running seed pipeline (full 30-day window)…[/bold green]" if seed \
        else "[bold green]Running pipeline…[/bold green]"
    with console.status(label):
        result = asyncio.run(run_pipeline(settings, db, seed=seed))

    new_count = result.get("new_items_count", 0)
    eml_path = result.get("eml_path", "")
    eml_sent = result.get("eml_sent", False)
    errors = result.get("errors", [])
    warnings = result.get("warnings", [])

    panel = Panel(
        f"[bold green]✓ Run complete[/bold green]\n\n"
        f"New items: [bold]{new_count}[/bold]\n"
        f".eml file: {eml_path or '(none — dry run or empty)'}\n"
        f"SMTP sent: {'yes' if eml_sent else 'no'}\n"
        f"Issues scanned: {result.get('issues_scanned', 0)}\n"
        f"Warnings: {len(warnings)}\n"
        f"Errors: {len(errors)}",
        title="gpjarmu-riport",
    )
    console.print(panel)
    if errors:
        console.print("[red]Errors:[/red]")
        for e in errors:
            console.print(f"  • {e}")


@app.command()
def run(
    seed: bool = typer.Option(
        False, "--seed", help="Seed run: ignore last_run, process full 30-day window."
    ),
):
    """Run the monthly Magyar Közlöny monitor pipeline."""
    _run_pipeline_and_report(seed=seed)


@app.command()
def seed():
    """
    Initial 30-day seed run.

    Same as `run --seed`. Processes the full 30-day lookback window
    regardless of the last_run stored in the state DB. Use this on
    the first run, or after `init-db --force`, to re-seed.
    """
    _run_pipeline_and_report(seed=True)


@app.command(name="init-db")
def init_db(
    force: bool = typer.Option(False, "--force", help="Reset all data first."),
):
    """Initialize (or reset) the state database."""
    settings = _setup_logging()
    db = StateDB(settings.state_db_path)
    if force:
        if typer.confirm(f"Delete all data from {settings.state_db_path}?"):
            db.reset()
            console.print(f"[green]✓ Reset state DB at {settings.state_db_path}[/green]")
    else:
        console.print(f"[green]✓ State DB initialized at {settings.state_db_path}[/green]")


@app.command(name="show-config")
def show_config():
    """Print the current configuration (redacted)."""
    settings = _setup_logging()
    data = settings.model_dump(mode="json")
    # Redact secrets
    for key in ("llm_api_key", "smtp_password"):
        if data.get(key):
            v = data[key]
            data[key] = v[:4] + "..." + v[-4:] if len(v) > 12 else "***"
    console.print_json(json.dumps(data, indent=2, ensure_ascii=False))


@app.command(name="show-state")
def show_state():
    """Print a summary of the state database."""
    settings = _setup_logging()
    db = StateDB(settings.state_db_path)
    meta = db.get_run_meta()
    issues = db.list_reported_in_window("1900-01-01", "2999-12-31")

    table = Table(title="Reported items (most recent first)")
    table.add_column("Issue")
    table.add_column("Anchor")
    table.add_column("Date")
    table.add_column("Score")
    table.add_column("Summary")

    for it in issues[:50]:
        table.add_row(
            it.issue_number,
            it.anchor,
            it.issue_date,
            f"{it.score:.2f}",
            (it.one_line_summary_hu or "")[:60],
        )
    console.print(table)
    console.print(f"\n[dim]last_run: {meta.get('last_run', '(never)')}  ·  total_reported: {meta.get('total_reported', '0')}[/dim]")


if __name__ == "__main__":
    app()
