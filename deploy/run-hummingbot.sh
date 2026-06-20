#!/usr/bin/env bash
# Wrapper: launches hummingbot_quickstart with the password read from env
# (HUMMINGBOT_PASSWORD) and never placed in argv.
#
# How it stays out of /proc/<pid>/cmdline:
#   - systemd's ExecStart line shows only this script + the public args
#     (--v2, --headless). No password.
#   - We exec `python -c "<preamble>" <args>` — the kernel records this
#     literal cmdline. The preamble reads HUMMINGBOT_PASSWORD at runtime
#     and mutates sys.argv inside the Python process to append
#     --config-password <pw> before importing the entry point.
#   - sys.argv mutation is in-process memory only; it does NOT update
#     /proc/<pid>/cmdline.
#
# Required env: HUMMINGBOT_PASSWORD
# Args: forwarded verbatim (e.g. --v2 factor_mm.yml --headless)

set -euo pipefail
: "${HUMMINGBOT_PASSWORD:?HUMMINGBOT_PASSWORD must be set}"

HB_DIR=/home/botuser/hummingbot
PY=/home/botuser/miniconda3/envs/hummingbot/bin/python

cd "$HB_DIR"

exec "$PY" -c '
import os, sys, runpy
pw = os.environ.pop("HUMMINGBOT_PASSWORD", None)
if not pw:
    raise SystemExit("[wrapper] HUMMINGBOT_PASSWORD missing")
sys.path.insert(0, os.path.abspath("bin"))   # hummingbot_quickstart.py uses sibling imports
sys.argv = ["hummingbot_quickstart.py"] + sys.argv[1:] + ["--config-password", pw]
runpy.run_path("bin/hummingbot_quickstart.py", run_name="__main__")
' "$@"
