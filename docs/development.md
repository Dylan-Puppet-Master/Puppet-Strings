# Development

## Layout

```
puppet_strings/
  names.py, model.py, config.py     identifiers, domain objects, config.toml
  sheets/                           one parser per sheet, CSV and Google Sheets sources, load_dataset
  skedge/                           grammar.lark, ast, parser, scope, resolve, validate
  solver/                           variables, structural constraints, compile, tiers, solve
  publish/                          staff view, clinic view, report, writer
  app/                              PySide6 request manager
  cli.py                            puppet-strings command
tests/                              pytest; fixtures/ holds a CSV export of every tab
docs/                               this site
```

The flow for a solve is `sheets.load.load_dataset` → `skedge.validate.validate_request` per
request → `solver.solve.solve` → `publish.writer.publish`. Each stage takes and returns
plain dataclasses from `model.py`; nothing holds global state.

## Running the tests

```
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

The app tests run headless with `QT_QPA_PLATFORM=offscreen`, which the test file sets.

## Refreshing the fixtures

`tests/fixtures` is a trimmed export. To refresh it from the real sheets:

```
puppet-strings export-fixtures /tmp/export
```

then copy and trim the tabs you need. Keep the fixture small; every parser test names
specific rows.

## Changing a sheet format

1. Change the parser in `puppet_strings/sheets/<sheet>.py`. Each is a pure function from a
   table (list of rows) to model objects, with a docstring describing the layout.
2. Update the fixture CSV and the test in `tests/test_sheets.py`.
3. Update [The sheets](sheets.md).

## Adding a Skills status

Add a row to `STATUS_WORDS` in `puppet_strings/sheets/skills.py`. If the status should be
able to supervise a scaffold, give it a `SkillStatus` whose `can_scaffold` is true in
`model.py`.

## Adding a Skedge feature

Grammar in `skedge/grammar.lark`; AST nodes in `skedge/ast.py`; the parser transformer in
`skedge/parser.py`; validation rules in `skedge/validate.py`; compilation in
`solver/compile.py`. Add a parser test, a validation test, and a solver test. Add the
construct to [Skedge reference](skedge.md); the docs test parses every example there.

## Releasing the docs

Pushing to `main` runs `.github/workflows/docs.yml`, which builds this site and deploys it
to GitHub Pages. Enable Pages for the repository once, with the `gh-pages` branch as source.
