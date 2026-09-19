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

## 3. Google OAuth client

Puppet Strings reads and writes the sheets as **you**, signed in to your Google account,
so a sheet you can open is a sheet it can open. Signing in needs an OAuth client, which is
made once and handed to the next Puppet Master along with this repository.

1. Open [console.cloud.google.com](https://console.cloud.google.com) and create a project
   named `Puppet Strings`.
2. **APIs & Services → Library**: enable **Google Sheets API** and **Google Drive API**.
3. **APIs & Services → OAuth consent screen**: set it up as an **Internal** app if camp
   has a Google Workspace, or **External** otherwise, and add yourself as a test user.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**, application
   type **Desktop app**. Download the JSON and save it as
   `~/.config/puppet_strings/oauth_client.json`.

Nothing needs sharing with anybody: you already have the sheets.

## 4. Create the two new spreadsheets

Create a **config spreadsheet** with tabs named `Blocks`, `Calendar`, `Requests`,
`Metrics` and, when you want it, `Adjustments`, with the exact columns in [The sheets](sheets.md). Each metric you add later gets
its own extra tab of ratings, as that page explains. The Blocks tab needs a `cabin_act`
row, which is the slot the cabin act sheets are scheduled into. Create an empty
**Published Schedules** spreadsheet. Choose both in the Configure pane.

## 5. Sign in and choose the sheets

```
puppet-strings app
```

The first run has nobody signed in, so the **Configure** pane opens before the window
does. Sign in — a browser opens and asks for consent once — and then use **Browse Drive…**
beside each row to pick that sheet. The browser shows My Drive, Shared with me and every
shared drive, the same three places Drive itself offers.

| Row | What to pick |
|---|---|
| Clinic Data, Clinic Schedule, Skills, Staff Categories | The existing spreadsheets |
| Config | The spreadsheet holding Blocks, Calendar, Requests, Metrics, Adjustments |
| Published Schedules | An empty spreadsheet for the days you publish |
| Cabin Acts | The **folder** holding one cabin act sheet per session and week |

What you choose is kept in `~/.config/puppet_strings/settings.json`. **Configure** is on
the right of the toolbar whenever you want to change a sheet, or sign in as a different
account.

## 6. config.toml, for everything else

Everything else lives in `~/.config/puppet_strings/config.toml`, and every part of it has a
default, so the file is only worth writing when you want to change something:

```toml
# Tab names inside each spreadsheet. Change these to match, or rename the tabs.
[tabs]
clinics          = "Clinics"      # Clinic_Data: the combined tab with a Category column
offerings        = "Offerings"    # Clinic_Schedule
skills           = "Skills"       # Skills: the main tab
position_skills  = "Positions"    # Skills: Clinic_Name | 1st | 2nd | 3rd
staff_categories = "Categories"   # Staff Categories
cabin_act_board  = "Board"        # the tab of a cabin act sheet that is read

[auth]
client_secrets = "~/.config/puppet_strings/oauth_client.json"
token          = "~/.config/puppet_strings/token.json"

[solver]
time_limit_seconds = 30   # the whole solve, not each tier
tidy_seconds = 2          # the cosmetic pass, which only neatens a working schedule
workers = 8

[views]
remainder = "DYOW/WPs"    # label for the unused part of a partly used block

[day]
midday = "12:00"          # where morning ends, for a half-day rest; 12:00 or 12 PM
```

A `[sheets]` table of spreadsheet ids still works, for an install made before the
Configure pane existed, and what is chosen in the app wins over it.

An older install may instead have a service account key at
`~/.config/puppet_strings/service_account.json`. That still works, and is used whenever
nobody is signed in, but it cannot browse Drive, so moving over to signing in is worth
doing.

## 7. Check

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
