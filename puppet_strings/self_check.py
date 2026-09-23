"""Import everything the app can reach: the packaged executable's check that nothing is missing.

A solve of the fixtures and the windows opened on them run offline, so they never load what
only signing in to Google loads, and a library the packaging left out of that shows up on
a Puppet Master's first sign-in instead of in the build. `puppet-strings self-check`
imports every module of the app and each library the app imports only inside a function,
and names every one that fails.
"""

import importlib
import pkgutil

import puppet_strings

# Imported inside a function, so only when somebody signs in, reads a sheet or opens Drive.
LATE = (
    "gspread",
    "gspread.utils",
    "google.auth.exceptions",
    "google.auth.transport.requests",
    "google.oauth2.credentials",
    "google.oauth2.service_account",
    "google_auth_oauthlib.flow",
)


def self_check() -> int:
    """Import it all and report what failed. Returns the exit code."""
    modules = [
        m.name
        for m in pkgutil.walk_packages(puppet_strings.__path__, "puppet_strings.")
        if not m.name.endswith("__main__")  # importing it would run the app
    ]
    failed = []
    for name in (*modules, *LATE):
        try:
            importlib.import_module(name)
        except Exception as e:  # noqa: BLE001 - every failure is the point
            failed.append(f"{name}: {type(e).__name__}: {e}")
    for line in failed:
        print(line)
    print(f"{len(modules) + len(LATE) - len(failed)} imported, {len(failed)} failed")
    return 1 if failed else 0
