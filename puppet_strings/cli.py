"""Command line: validate requests, list names, solve a date, export fixtures, open the app."""

import argparse
import sys
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from puppet_strings import __version__
from puppet_strings.config import Config, load_config
from puppet_strings.generate import generated_requests, has_offerings_loaded, is_generated
from puppet_strings.google_auth import AuthError
from puppet_strings.model import Dataset
from puppet_strings.publish.views import changes_view, clinic_view, report, staff_view
from puppet_strings.publish.writer import day_sheet, is_published, publish
from puppet_strings.requests_db import FIXTURE_FILE, RequestDb, open_requests
from puppet_strings.session import open_source
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.source import CsvSource, LoadError, Source, Table
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import name_listing
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.solve import RequestError, solve

SHEETS = ("clinic_data", "clinic_schedule", "skills", "config")


def main(argv: list[str] | None = None) -> int:
    """Entry point for `puppet-strings`."""
    parser = argparse.ArgumentParser(prog="puppet-strings", description="Camp Augusta scheduling")
    parser.add_argument("--config", type=Path, help="config.toml path")
    parser.add_argument(
        "--fixtures", type=Path, help="read CSV files from this folder instead of Google Sheets"
    )
    parser.add_argument("--date", type=date.fromisoformat, help="target date, default tomorrow")
    parser.add_argument(
        "--no-cache", action="store_true", help="read every sheet from Google, not the cache"
    )
    parser.add_argument("--version", action="version", version=__version__)
    # Not required: a downloaded release is opened by double-clicking it, and what that
    # should do is open the window, not print the usage of a command line nobody typed.
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("validate", help="check every request for the target date")
    commands.add_parser("load-offerings", help="add the Offerings tab's clinics to the requests")
    commands.add_parser("names", help="list every valid Skedge name")
    export_requests = commands.add_parser(
        "export-requests", help="copy the requests to a file for another Puppet Master"
    )
    export_requests.add_argument("file", type=Path)
    import_requests = commands.add_parser(
        "import-requests", help="replace the requests with a file another Puppet Master exported"
    )
    import_requests.add_argument("file", type=Path)
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
    commands.add_parser("app", help="open the desktop request manager (the default)")
    commands.add_parser("train", help="practise writing Skedge, offline, on a real session")
    commands.add_parser("self-check", help="import everything, to check an install is whole")
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
    if args.command == "self-check":
        from puppet_strings.self_check import self_check

        return self_check()
    if args.command == "train":
        from puppet_strings.training.app import run_training

        return run_training()
    if args.no_cache:
        config = replace(config, cache=None)
    if args.command in (None, "app"):
        from puppet_strings.app.main import run_app

        return run_app(config, args.fixtures)
    if args.command in ("export-requests", "import-requests"):
        # the requests file needs no Google account to read or replace
        book = open_requests(config, CsvSource(args.fixtures) if args.fixtures else None)
        if args.command == "export-requests":
            return _export_requests(book, args.file)
        return _import_requests(book, args.file)
    source = open_source(config, args.fixtures)
    if args.command == "export-fixtures":
        return _export(source, open_requests(config, source), args.folder)
    dataset = load_dataset(source, config, target)
    for warning in dataset.warnings:
        print(f"warning: {warning}")
    if args.command == "names":
        return _names(dataset)
    if args.command == "validate":
        return _validate(dataset)
    if args.command == "load-offerings":
        return _load_offerings(source, config, dataset)
    if args.same_day and dataset.baseline is None:
        print(f"error: {dataset.target} has no published schedule to change", file=sys.stderr)
        return 1
    if not has_offerings_loaded(dataset.requests, dataset.target):
        print(f"warning: no offerings loaded for {dataset.target}; run load-offerings first")
    for adjustment in dataset.today_adjustments:
        print(f"today: {adjustment.describe(dataset.staff[adjustment.staff].name)}")
    return _solve(source, config, dataset, args)


def _export_requests(book: RequestDb, target: Path) -> int:
    print(f"exported {book.export(target)} requests to {target}")
    return 0


def _import_requests(book: RequestDb, file: Path) -> int:
    count, kept = book.import_file(file)
    print(f"imported {count} requests from {file}")
    if kept is not None:
        print(f"the requests they replaced are in {kept}")
    return 0


def _export(source: Source, book: RequestDb, folder: Path) -> int:
    """Every tab as CSV, and the requests beside them, so the folder is a whole session."""
    target = CsvSource(folder)
    for sheet in SHEETS:
        for tab in source.tabs(sheet):
            target.write(sheet, tab, source.read(sheet, tab))
            print(f"{sheet}/{tab}")
    print(f"{book.export(folder / FIXTURE_FILE)} requests to {FIXTURE_FILE}")
    return 0


def _names(dataset: Dataset) -> int:
    for namespace, names in name_listing(dataset).items():
        print(namespace)
        for name, note in names:
            print(f"  {namespace}.{name}  ({note})")
    return 0


def _load_offerings(source: Source, config: Config, dataset: Dataset) -> int:
    day_sheet(source, config, dataset.this_span, dataset.target)  # made if it is not there yet
    generated = generated_requests(dataset)
    book = open_requests(config, source)
    book.delete(r.id for r in dataset.requests if is_generated(r, dataset.target))
    book.put(generated)
    print(f"loaded {len(generated)} offerings for {dataset.target}")
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
    _print_table(staff_view(dataset, result.assignments, config.remainder).rows)
    print()
    _print_table(clinic_view(dataset, result.assignments, config.remainder).rows)
    print()
    _print_table(report(result))
    if args.same_day:
        print()
        _print_table(changes_view(dataset, result))
    if not args.publish:
        return 0
    if is_published(source, config, dataset) and not (args.force or args.same_day):
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
