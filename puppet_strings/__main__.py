"""Entry point for `python -m puppet_strings` and for the packaged executable."""

from puppet_strings.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
