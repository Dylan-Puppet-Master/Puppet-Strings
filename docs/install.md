# Install and set up

## For the Puppet Master

1. Download the file for your computer from the
   [releases page](https://github.com/Dylan-Puppet-Master/Puppet-Strings/releases):
   `puppet-strings-windows.exe`, `puppet-strings-macos` or `puppet-strings-linux.tar.gz`.
2. Put it somewhere you will find it again, and open it. On macOS you may have to mark it
   runnable first (`chmod +x puppet-strings-macos`). On Linux, unpack the archive
   (`tar xzf puppet-strings-linux.tar.gz`) into the folder you want to keep it in and run
   `./puppet-strings-linux/install.sh`, which marks the program runnable and puts Puppet
   Strings in your applications menu with its icon. Keep the folder where it is: the menu
   entry points at it.
3. Sign in with the Google account that can open camp's sheets, and choose the **Puppet
   Strings** folder in **Configure**. Puppet Strings remembers both.

There is no config file to put anywhere and no OAuth client JSON to go and find:
everything that is the same for everyone — the Google client, the update feed — is built
into the file you downloaded, and what differs from one person to the next is your sign-in
and your folder, which it remembers for you.

**Check for updates** at the right-hand end of the toolbar asks GitHub whether a newer
version is out and replaces the file you are running if you say yes; restart it afterwards.
A downloaded copy also asks quietly the first time it loads a day, and says nothing unless
there is something newer.

On Linux the update is the same archive the releases page has, so it is unpacked and the
program inside it replaces the one you are running, in the folder it is already in. The
icon beside it is refreshed at the same time, and your menu entry is left alone — it names
that same folder and goes on working. There is no need to run `install.sh` again.

## Building the releases, once

Puppet Strings signs in as the person using it, which needs a Google OAuth client made
once and built into the releases. Steps 3 and 4 below make one; then, in the GitHub
repository under **Settings → Secrets and variables → Actions**, add `GOOGLE_CLIENT_ID`
and `GOOGLE_CLIENT_SECRET`. `RELEASES_URL` is optional and only needed to point a build at
a different repository's releases.

Push a tag and the release is built for all three platforms with camp's settings inside:

```
git tag v0.2.0 && git push --tags
```

!!! note
    A Google client secret for a desktop app is not confidential in the usual sense — it
    ships inside every copy of every desktop program that signs in to Google, and Google
    says as much. It is kept in a repository secret rather than in the code anyway,
    because a published one lets someone put camp's name on a consent screen of their own.

## Running from source

The rest of this page is for working on Puppet Strings rather than using it. A checkout
has no built-in client, so it reads `config.toml` and the OAuth client JSON as it always
has, and it never checks for updates on its own — `git pull` is the update.

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

## 4. Create the config spreadsheet and the schedules folder

Create a **config spreadsheet** with tabs named `Blocks`, `Calendar`, `Mappings` and, when
you want it, `Adjustments`, with the exact columns in [The sheets](sheets.md). Each mapping
you add later gets its own extra tab of rows, as that page explains. The Blocks tab
needs a `cabin_act` row, which is the slot the cabin act sheets are scheduled into.

Requests need no spreadsheet: they are kept on this computer. See
[Requests](sheets.md#requests-on-this-computer), which also says how to hand them over.

Put the config spreadsheet, and the other spreadsheets, in a **Puppet Strings** folder holding a folder per
year. Puppet Strings builds the programme and span folders inside a year as it needs them;
you put a `Staff Categories` spreadsheet in each span's folder, and **Load offerings** makes
the day spreadsheets. See [the schedules tree](sheets.md#the-schedules-tree).

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
| Root | The **directory** holding a folder per year; see [the schedules tree](sheets.md#the-schedules-tree) |
| Cabin Acts | The **directory** holding one cabin act sheet per session and week, which somebody else keeps |

Two directories is the whole of it. Inside the root everything is found by name — a spreadsheet called `Clinic_Data`, `Clinic_Schedule`, `Skills` or `Config` is that
sheet, a folder called `2027` is that year — so renaming a sheet is how you move it, and
nothing has to be re-chosen when you add next season.

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
cabin_act_board  = "Board"        # the tab of a cabin act sheet that is read

[auth]
client_secrets = "~/.config/puppet_strings/oauth_client.json"
token          = "~/.config/puppet_strings/token.json"
# A release has camp's OAuth client built in; these override it, and are how a checkout
# signs in without a client JSON file.
# client_id     = "..."
# client_secret = "..."

[updates]
releases_url = "https://api.github.com/repos/Dylan-Puppet-Master/Puppet-Strings/releases/latest"

[solver]
tier_seconds_limit = 15   # each pass, not the whole solve
tidy_seconds = 2          # the cosmetic pass, which only neatens a working schedule
workers = 8

[views]
remainder = "DYOW/WPs"    # label for the unused part of a partly used block

[day]
midday = "12:00"          # where morning ends, for a half-day rest; 12:00 or 12 PM
date_order = "mdy"        # how to read 6/7/2026 on the Calendar: "mdy" or "dmy"
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
`load-offerings` makes the date's spreadsheet if it is not there yet and throws away
edited clinics, so the date's clinics are its Offerings tab's again. `solve` prints the
schedule for a date without publishing it, with a clinic request for each offering. If any command reports a
load error, it names the sheet, tab and row to fix.

## Working offline

`puppet-strings export-fixtures some-folder` downloads every tab as CSV, and copies the
requests in beside them as `requests.sqlite`. Every command then accepts
`--fixtures some-folder` to run without Google access, which is also how the test suite
works. Running on the folder reads and saves its own requests, not this computer's.

## The Google Sheets cache

Each sheet read from Google is kept in `~/.config/puppet_strings/sheets-cache.sqlite`
until Drive says it has changed, so a reload reads only what somebody has edited since.
Drive can take a moment to notice an edit; if a sheet you have just changed comes back as
it was, **Configure → Google Sheets cache → Clear** reads everything afresh. From the
command line, `--no-cache` does the same for one run. To turn the cache off for good, set
`cache = ""` under `[storage]` in config.toml.
