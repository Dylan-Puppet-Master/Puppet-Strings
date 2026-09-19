"""Command line: validate requests, list names, solve a date, export fixtures, open the app."""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from puppet_strings.cabin_acts import cabin_act_requests
from puppet_strings.cabin_acts import merge as merge_cabin_acts
from puppet_strings.config import Config, load_config
from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.google_auth import AuthError
from puppet_strings.model import Dataset
from puppet_strings.publish.views import changes_view, clinic_view, report, staff_view
from puppet_strings.publish.writer import is_published, publish
from puppet_strings.session import open_source
from puppet_strings.sheets.cabin_acts import parse_board
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.requests import request_rows
from puppet_strings.sheets.source import CsvSource, LoadError, Source, Table
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import name_listing
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.solve import RequestError, solve

SHEETS = ("clinic_data", "clinic_schedule", "skills", "staff_categories", "config", "published")
CABIN_ACTS_FOLDER = "cabin_acts"


def main(argv: list[str] | None = None) -> int:
    """Entry point for `puppet-strings`."""
    parser = argparse.ArgumentParser(prog="puppet-strings", description="Camp Augusta scheduling")
    parser.add_argument("--config", type=Path, help="config.toml path")
    parser.add_argument(
        "--fixtures", type=Path, help="read CSV files from this folder instead of Google Sheets"
    )
    parser.add_argument("--date", type=date.fromisoformat, help="target date, default tomorrow")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("validate", help="check every request on the Requests sheet")
    commands.add_parser(
        "load-offerings", help="add the Offerings tab's clinics to the Requests sheet"
    )
    commands.add_parser(
        "import-cabin-acts", help="rebuild the cabin act requests from the cabin act sheets"
    )
    commands.add_parser("names", help="list every valid Skedge name")
    solve_parser = commands.add_parser("solve", help="build the schedule for the target date")
    solve_parser.add_argument("--publish", action="store_true", help="write to Published Schedules")
    solve_parser.add_argument(
        "--same-day",
        action="store_true",
        help="re-solve a published day, keeping it as close to what was published as it can",
    )
    solve_parser.add_argument(
        "--force", action="store_true", help="overwrite an already published date"
    )
    export = commands.add_parser("export-fixtures", help="download every tab as CSV")
    export.add_argument("folder", type=Path)
    commands.add_parser("app", help="open the desktop request manager")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    default = date.today() if getattr(args, "same_day", False) else date.today() + timedelta(days=1)
    target = args.date or default
    try:
        return _run(args, config, target)
    except (LoadError, RequestError, AuthError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(args, config: Config, target: date) -> int:
    if args.command == "app":
        from puppet_strings.app.main import run_app

        return run_app(config, args.fixtures)
    source = open_source(config, args.fixtures)
    if args.command == "export-fixtures":
        return _export(source, args.folder)
    dataset = load_dataset(source, config, target)
    for warning in dataset.warnings:
        print(f"warning: {warning}")
    if args.command == "names":
        return _names(dataset)
    if args.command == "validate":
        return _validate(dataset)
    if args.command == "load-offerings":
        return _load_offerings(source, config, dataset)
    if args.command == "import-cabin-acts":
        return _import_cabin_acts(source, config, dataset)
    if args.same_day and dataset.baseline is None:
        print(f"error: {dataset.target} has no published schedule to change", file=sys.stderr)
        return 1
    if not has_offerings_loaded(dataset.requests, dataset.target):
        print(f"warning: no offerings loaded for {dataset.target}; run load-offerings first")
    for adjustment in dataset.today_adjustments:
        print(f"today: {adjustment.describe(dataset.staff[adjustment.staff].name)}")
    return _solve(source, config, dataset, args)


def _export(source: Source, folder: Path) -> int:
    target = CsvSource(folder)
    for sheet in SHEETS:
        for tab in source.tabs(sheet):
            target.write(sheet, tab, source.read(sheet, tab))
            print(f"{sheet}/{tab}")
    return 0


def _names(dataset: Dataset) -> int:
    for namespace, names in name_listing(dataset).items():
        print(namespace)
        for name, note in names:
            print(f"  {namespace}.{name}  ({note})")
    return 0


def _load_offerings(source: Source, config: Config, dataset: Dataset) -> int:
    generated = generated_requests(dataset)
    merged = merge(list(dataset.requests), generated, dataset.target)
    source.write("config", config.tabs["requests"], request_rows(tuple(merged)))
    print(f"loaded {len(generated)} offerings for {dataset.target} into the Requests sheet")
    return 0


def _import_cabin_acts(source: Source, config: Config, dataset: Dataset) -> int:
    """Read every cabin act sheet in the folder and rewrite the cabin act requests."""
    tables = source.read_group(CABIN_ACTS_FOLDER, config.tabs["cabin_act_board"])
    boards = {title: parse_board(table, title) for title, table in tables.items()}
    generated, warnings = cabin_act_requests(boards, dataset)
    for warning in warnings:
        print(f"warning: {warning}")
    merged = merge_cabin_acts(list(dataset.requests), generated)
    source.write("config", config.tabs["requests"], request_rows(tuple(merged)))
    print(f"imported {len(generated)} cabin acts from {len(boards)} sheet(s)")
    return 0


def _validate(dataset: Dataset) -> int:
    failures = 0
    for request in dataset.requests:
        try:
            validate_request(request, dataset)
        except SkedgeError as e:
            failures += 1
            print(f"{request.id}: {e}")
    print(f"{len(dataset.requests) - failures} of {len(dataset.requests)} requests valid")
    return 1 if failures else 0


def _solve(source: Source, config: Config, dataset: Dataset, args) -> int:
    result = solve(dataset, config, same_day=args.same_day)
    if not result.feasible:
        print("No schedule: these MUST_HAPPEN requests conflict:")
        for request_id in result.conflicts:
            print(f"  {request_id}")
        return 1
    _print_table(staff_view(dataset, result.assignments, config.remainder))
    print()
    _print_table(clinic_view(dataset, result.assignments, config.remainder).rows)
    print()
    _print_table(report(result))
    if args.same_day:
        print()
        _print_table(changes_view(dataset, result))
    if not args.publish:
        return 0
    if is_published(source, dataset) and not (args.force or args.same_day):
        print(f"{dataset.target} is already published; use --force to overwrite", file=sys.stderr)
        return 1
    publish(source, config, dataset, result)
    print(f"published {dataset.target}")
    return 0


def _print_table(table: Table) -> None:
    if not table:
        return
    width = max(len(row) for row in table)
    cells = [
        [str(c).replace("\n", " / ") for c in row] + [""] * (width - len(row)) for row in table
    ]
    widths = [max(len(row[i]) for row in cells) for i in range(width)]
    for row in cells:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip())
