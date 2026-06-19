# Deploy notes — TODOs not yet folded into the scripts

## bootstrap_vps.sh fixes pending after first VPS bring-up (2026-06-20)

### Issue 1 — Hummingbot `./install` fails on newer Miniconda

Newer Miniconda (2024+) ships **without** `conda-build`, which provides
`conda develop`. Hummingbot's `./install` uses both `conda develop` and
`pre-commit` and fails on:

```
conda: error: argument COMMAND: invalid choice: 'develop' ...
./install: line 68: pre-commit: command not found
```

**Fix:** in step 3b, after `conda activate hummingbot` and before `./install`,
inject:

```bash
conda install -y conda-build
pip install pre-commit
```

### Issue 2 — `./install` + `./compile` inside the clone guard means re-run won't recover

Current step 3b:

```bash
if [ ! -d hummingbot ]; then
  git clone ...
  cd hummingbot
  ./install
  ./compile
fi
```

If `./install` or `./compile` fails after the clone succeeds, re-running
`bootstrap_vps.sh` SKIPS the install/compile (because `~/hummingbot` exists).
Operator must recover manually.

**Fix:** factor install/compile out of the clone guard and add their own
sentinel files (e.g. `~/hummingbot/.install.ok`, `~/hummingbot/.compile.ok`)
so each step is independently idempotent.

### Issue 3 — README symlink list is stale

The README's first-run runbook lists 5 controller files to be symlinked.
After 2026-06-19 we have 6 (added `exchange_time.py`). Bootstrap was
patched to loop over `*.py` (commit 7e0b500) — README runbook should
match the loop wording.
