# Install and set up

## 1. Python

Puppet Strings needs Python 3.12 or newer. Check with:

```
python3 --version
```

## 2. Install the package

From a copy of this repository:

```
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
puppet-strings --help
```

On Windows use `.venv\Scripts\activate`.

## 3. Google Cloud service account

The tool reads and writes Google Sheets as a **service account**: a robot user with its
own email address. Set it up once; hand the key file to the next Puppet Master.

1. Open [console.cloud.google.com](https://console.cloud.google.com) and create a project
   named `Puppet Strings`.
2. **APIs & Services → Library**: enable **Google Sheets API** and **Google Drive API**.
3. **IAM & Admin → Service Accounts → Create service account**. Name it `puppet-strings`.
   No roles are needed.
4. Open the new account, **Keys → Add key → Create new key → JSON**. Save the download as
   `~/.config/puppet_strings/service_account.json`.
5. Open the JSON file and copy the `client_email` address. **Share** each spreadsheet with
   that address:

   | Spreadsheet | Access |
   |---|---|
   | Clinic_Data, Clinic_Schedule, Skills, Staff Categories | Viewer |
   | The config spreadsheet (Blocks, Calendar, Requests, Metrics) | Editor |
   | Published Schedules | Editor |

## 4. Config file

Create `~/.config/puppet_strings/config.toml`:

```toml
[sheets]
clinic_data      = "1bcCFIBqL77HbPiY1nOM2cqzZ0YC9fhRcdBi4TwZS0-E"
clinic_schedule  = "1h_iOC7oqe43QFkpgoS-D-oFzP_r8G1EtDmrxvc83-o8"
skills           = "1SAjIEMtNwdpDWcKkBp8wrEt9BjQJ6kaeHW00zJcBQPs"
staff_categories = "1Z92mJG-AbXKBX_jq5DKztNLVDXPUyL-licZWGvkVPXs"
config           = "<id of the config spreadsheet>"
published        = "<id of the Published Schedules spreadsheet>"

# Tab names inside each spreadsheet. Change these to match, or rename the tabs.
[tabs]
clinics          = "Clinics"      # Clinic_Data: the combined tab with a Category column
offerings        = "Offerings"    # Clinic_Schedule
skills           = "Skills"       # Skills: the main tab
position_skills  = "Positions"    # Skills: Clinic_Name | 1st | 2nd | 3rd
staff_categories = "Categories"   # Staff Categories

[auth]
credentials = "~/.config/puppet_strings/service_account.json"

[solver]
time_limit_seconds = 30   # per priority tier
tidy_seconds = 2          # per cosmetic pass, which only neatens a working schedule
workers = 8

[views]
remainder = "DYOW/WPs"    # label for the unused part of a partly used block
```

A spreadsheet's id is the long string in its URL between `/d/` and `/edit`.

## 5. Create the two new spreadsheets

Create a **config spreadsheet** with tabs named `Blocks`, `Calendar`, `Requests`,
`Metrics` and, when you want it, `Adjustments`, with the exact columns in [The sheets](sheets.md). Each metric you add later gets
its own extra tab of ratings, as that page explains. Create an empty **Published
Schedules** spreadsheet. Put both ids in `config.toml`.

## 6. Check

```
puppet-strings names
puppet-strings validate
puppet-strings --date 2026-06-15 load-offerings
puppet-strings --date 2026-06-15 solve
```

`names` lists every name you can use in a request. `validate` checks every request.
`load-offerings` turns the Offerings tab into requests for that date, replacing ones
loaded before. `solve` prints the
schedule for a date without publishing it. If any command reports a
load error, it names the sheet, tab and row to fix.

## Working offline

`puppet-strings export-fixtures some-folder` downloads every tab as CSV. Every command then
accepts `--fixtures some-folder` to run without Google access, which is also how the test
suite works.
