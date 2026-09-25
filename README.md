# Puppet Strings

Staff schedule automation for Camp Augusta. The Puppet Master keeps camp data in Google
Sheets, writes scheduling rules as requests in a small language called Skedge, and the
solver (Google OR-Tools CP-SAT) produces and publishes the day's schedule.

Full documentation: the `docs/` folder, published with MkDocs to GitHub Pages.

![The request manager's canvas](docs/img/canvas.png)

## Code layout

| Module | Does |
|---|---|
| `puppet_strings/model.py` | Domain objects: Staff, Activity, Block, Request, Dataset, Assignment |
| `puppet_strings/sheets/` | Reads every sheet into a Dataset, cached by Drive version; writes published schedules |
| `puppet_strings/requests_db.py` | The requests, kept on this computer in one SQLite file, each scoped to a day, week, session or season |
| `puppet_strings/drive.py`, `google_auth.py`, `settings.py` | Signing in to Google, browsing Drive, and which sheets were chosen |
| `puppet_strings/backup.py` | A snapshot of the requests, copied to `Database Backups` on Drive |
| `puppet_strings/skedge/` | The Skedge language: grammar, parser, name resolution, validation |
| `puppet_strings/solver/` | Compiles requests to CP-SAT and solves tier by tier |
| `puppet_strings/publish/` | Renders the staff view, clinic view and report |
| `puppet_strings/app/` | The desktop request manager |
| `puppet_strings/training/` | The Skedge trainer (`puppet-strings train`) and its bundled session |
| `puppet_strings/cli.py` | The `puppet-strings` command |

## Install

```
git clone <this repository>
cd puppet_strings
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Then follow `docs/install.md` to make the Google OAuth client, create the Blocks,
Calendar and Mappings tabs, and open `puppet-strings app` to sign in and choose the
Puppet Strings folder from Drive.

## Use

```
puppet-strings names                     # every name you can write in a request
puppet-strings validate                  # check every request the day reads
puppet-strings --date 2026-06-15 solve   # print tomorrow's schedule
puppet-strings solve --publish           # and write it to the day's own sheet
puppet-strings solve --same-day          # re-solve a published day, moving as few people as it can
puppet-strings backup-requests           # copy the requests to Database Backups on Drive
puppet-strings app                       # open the request manager
puppet-strings train                     # practise writing Skedge, offline
```

Every command accepts `--fixtures FOLDER` to run from CSV files instead of Google Sheets;
`puppet-strings export-fixtures FOLDER` creates such a folder.

## Develop

```
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
mkdocs serve
```

The test suite runs entirely offline against `tests/fixtures`.
