"""Command line: validate requests, list names, solve a date, export fixtures, open the app."""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from puppet_strings.config import Config, load_config
from puppet_strings.generate import generated_requests, has_offerings_loaded, merge
from puppet_strings.model import Dataset
from puppet_strings.publish.views import clinic_view, report, staff_view
from puppet_strings.publish.writer import is_published, publish
from puppet_strings.sheets.load import load_dataset
from puppet_strings.sheets.requests import request_rows
from puppet_strings.sheets.source import CsvSource, LoadError, SheetsSource, Source, Table
from puppet_strings.skedge.ast import SkedgeError
from puppet_strings.skedge.resolve import date_names
from puppet_strings.skedge.validate import validate_request
from puppet_strings.solver.solve import RequestError, solve

SHEETS = ("clinic_data", "clinic_schedule", "skills", "staff_categories", "config", "published")


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
    commands.add_parser("names", help="list every valid Skedge name")
    solve_parser = commands.add_parser("solve", help="build the schedule for the target date")
    solve_parser.add_argument("--publish", action="store_true", help="write to Published Schedules")
    solve_parser.add_argument(
        "--force", action="store_true", help="overwrite an already published date"
    )
    export = commands.add_parser("export-fixtures", help="download every tab as CSV")
    export.add_argument("folder", type=Path)
    commands.add_parser("app", help="open the desktop request manager")
    args = parser.parse_args(argv)

    config = load_config(args.config)
    target = args.date or date.today() + timedelta(days=1)
    try:
        return _run(args, config, target)
    except (LoadError, RequestError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def _run(args, config: Config, target: date) -> int:
    if args.command == "app":
        from puppet_strings.app.main import run_app

        return run_app(config, args.fixtures)
    source = _source(args.fixtures, config)
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
    if not has_offerings_loaded(dataset.requests, dataset.target):
        print(f"warning: no offerings loaded for {dataset.target}; run load-offerings first")
    return _solve(source, config, dataset, args.publish, args.force)


def _source(fixtures: Path | None, config: Config) -> Source:
    if fixtures:
        return CsvSource(fixtures)
    return SheetsSource(config.sheets, config.credentials)


def _export(source: Source, folder: Path) -> int:
    target = CsvSource(folder)
    for sheet in SHEETS:
        for tab in source.tabs(sheet):
            target.write(sheet, tab, source.read(sheet, tab))
            print(f"{sheet}/{tab}")
    return 0


def _names(dataset: Dataset) -> int:
    spaces = {
        "staff": {
            **{i: s.name for i, s in dataset.staff.items()},
            **_categories(dataset.staff_categories),
        },
        "activity": {
            **{i: a.name for i, a in dataset.activities.items()},
            **_categories(dataset.activity_categories),
        },
        "block": {**{i: "" for i in dataset.blocks}, **_categories(dataset.block_categories)},
        "date": {name: _dates(days) for name, days in date_names(dataset).items()},
        "role": {
            "first, second, third": "positions",
            "lifeguard, lifeguard_2": "extra lifeguards on water clinics",
            "shadow, scaffolded, trainee": "",
        },
        "metric": {m: "" for m in dataset.metrics},
    }
    for namespace, names in spaces.items():
        print(namespace)
        for name, note in sorted(names.items()):
            print(f"  {namespace}.{name}" + (f"  ({note})" if note else ""))
    return 0


def _dates(days) -> str:
    return next(iter(days)).isoformat() if len(days) == 1 else f"{len(days)} dates"


def _categories(categories) -> dict[str, str]:
    return {name: f"category, {len(members)} members" for name, members in categories.items()}


def _load_offerings(source: Source, config: Config, dataset: Dataset) -> int:
    generated = generated_requests(dataset)
    merged = merge(list(dataset.requests), generated, dataset.target)
    source.write("config", config.tabs["requests"], request_rows(tuple(merged)))
    print(f"loaded {len(generated)} offerings for {dataset.target} into the Requests sheet")
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


def _solve(source: Source, config: Config, dataset: Dataset, do_publish: bool, force: bool) -> int:
    result = solve(dataset, config)
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
    if not do_publish:
        return 0
    if is_published(source, dataset) and not force:
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
