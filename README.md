# Lottery Archive

Validated CSV archives and scheduled collectors for Austrian Lotto 6 aus 45,
German Lotto 6 aus 49, EuroMillions, and Eurojackpot. A static page shows each
game’s latest recorded result and offers complete CSV downloads.

## Included archives

Snapshot checked on **2026-09-20**. The 2026 files contain published results to
the dates below; remaining 2026 draws are added as they occur.

Version **1.2.0** retains Austrian and German Lotto draws from **2000-01-01 onward**,
inclusive. EuroMillions and Eurojackpot retain their complete existing
histories, starting in 2004 and 2012 respectively.

| Game | CSV | First archived draw | Latest stored draw | Records |
| --- | --- | --- | --- | ---: |
| Austrian Lotto 6 aus 45 | [`at/lotto_6aus45/results.csv`](at/lotto_6aus45/results.csv) | 2000-01-02 | 2026-09-18 | 2,868 |
| German Lotto 6 aus 49 | [`de/lotto_6aus49/results.csv`](de/lotto_6aus49/results.csv) | 2000-01-01 | 2026-09-19 | 2,741 |
| EuroMillions | [`eu/euromillions/results.csv`](eu/euromillions/results.csv) | 2004-02-13 | 2026-09-18 | 1,982 |
| Eurojackpot | [`eu/eurojackpot/results.csv`](eu/eurojackpot/results.csv) | 2012-03-23 | 2026-09-18 | 991 |

## Quick start

Python **3.11 or later** is required. The default in `.python-version` is **3.14**;
CI covers Python 3.11, 3.12, 3.13, and 3.14. The recommended dependency manager,
**uv**, is pinned to **0.12.17** in CI. It installs the exact versions and hashes
recorded in `uv.lock`.

From the extracted project directory:

```bash
uv sync --locked
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/check_integrity.py --skip-stale
uv run --locked python scripts/update_all.py
uv run --locked python scripts/check_integrity.py
uv run --locked python scripts/generate_page.py
```

Open `public/index.html`, or serve the generated page locally:

```bash
uv run --locked python -m http.server 8000 --directory public
```

Then open `http://localhost:8000`. The generator copies the canonical archives
from `at/`, `de/`, and `eu/` into `public/`, keeping every download link portable.

If using pip instead of uv:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e .
python scripts/update_all.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`. The pip route
uses pinned direct dependencies; uv also locks transitive dependencies.
Collectors resolve data paths relative to their scripts, independent of the
shell's working directory.

## Updates, historical imports, and commits

```bash
# All four games; works without a Git repository.
uv run --locked python scripts/update_all.py

# Re-download each game's supported archive history.
uv run --locked python scripts/update_all.py --init

# In a Git checkout, also commit each changed game separately.
uv run --locked python scripts/update_all.py --commit

# Individual collectors.
uv run --locked python scripts/fetch_lotto_at_6aus45.py
uv run --locked python scripts/fetch_lotto_de_6aus49.py
uv run --locked python scripts/fetch_euromillions.py
uv run --locked python scripts/fetch_eurojackpot.py
```

Each collector accepts `--init` and `--commit`, which can be combined. Regular
updates inspect recent years; `--init` revisits the configured archive history:
2000 onward for Austrian/German Lotto, 2004 onward for EuroMillions, and 2012
onward for Eurojackpot. Full imports take longer than regular updates.

The Lotto cutoff is defined once in `scripts/archive_policy.py` and enforced by
collectors, CSV validation, the integrity checker, and page generation. German
imports never request years before 2000. Austria's bundled historical source
still contains older years; its parser skips those sections before parsing
draws. Initialization and automatic bootstrap cannot reintroduce pre-2000 rows.

This release removes **814 Austrian** and **2,307 German** pre-2000 records; every
retained date and number matches version 1.1.0. When updating an existing checkout,
include both results CSVs from this release along with the code. An older CSV
restored manually is rejected with an archive-start error, preserving its bytes
for review instead of silently merging unsupported records. The generated Lotto
download links explicitly identify their 2000 start year.

**German coverage in 2000:** the combined archive contains Saturday draws from
2000-01-01 and Wednesday draws from 2000-12-06. The former separate Wednesday
lottery is outside this dataset, so 2000 contains 57 records: 53 Saturdays and
four December Wednesdays. [LOTTO Bayern's archive description](https://www.lotto-bayern.de/lotto6aus49/gewinnzahlen)
and [game history](https://www.lotto-bayern.de/lotto6aus49/normalschein) confirm the
transition. The integrity checker applies that historical schedule.

**Behavior change:** `update_all.py` writes data without committing by default.
Use `--commit` explicitly to retain the original automatic-commit behavior.
Commits include only the selected results CSV and preserve unrelated staged
files. If a write succeeds but its commit fails, a later `--commit` invocation
can retry the pending file even when the source has no newer draw.

The combined updater attempts every game even if another fails. Fetch, parsing,
write, or requested commit failures produce a nonzero process exit code. A valid
update with no new results succeeds. A failed collector does not prevent the
other collectors from updating.

## Eurojackpot: 2012–2026 and future years

The collector uses the requested source and year routing:

- **Current calendar year:** [`eurojackpot-zahlenarchiv.php`](https://www.eurojackpot-zahlen.eu/eurojackpot-zahlenarchiv.php), without a query parameter.
- **Previous years:** [`eurojackpot-zahlenarchiv.php?j=2012`](https://www.eurojackpot-zahlen.eu/eurojackpot-zahlenarchiv.php?j=2012), substituting the required year.

The current year is calculated at runtime. In 2027, 2026 is fetched using
`?j=2026`, and the bare URL is used for 2027.

```bash
# Complete history from 2012 to the current year.
uv run --locked python scripts/fetch_eurojackpot.py --init

# Explicit inclusive range requested for this update.
uv run --locked python scripts/fetch_eurojackpot.py --start-year 2012 --end-year 2026

# Recheck one historical year.
uv run --locked python scripts/fetch_eurojackpot.py --start-year 2014 --end-year 2014
```

Explicit year bounds cannot be combined with `--init`. Years before 2012, future
years, and reversed ranges are rejected. A missing Eurojackpot CSV automatically
bootstraps the complete history. Regular updates also detect incomplete older
years and resume from the first gap. New or corrected source records are merged
by draw date, making repeated imports idempotent.

The parser reads draw rows inside `#gewinnzahlen` and uses the visible
`DD.MM.YYYY` date: the source's HTML `datetime` attribute currently has its day
and month swapped (`YYYY-DD-MM`). It checks the page year, dates, number counts,
distinct numbers, historical limits, and draw schedule.

| Draw dates | Main numbers | Euro numbers | Draw days |
| --- | --- | --- | --- |
| 2012-03-23 through 2014-10-03 | 5 from 1–50 | 2 from 1–8 | Friday |
| 2014-10-10 through 2022-03-18 | 5 from 1–50 | 2 from 1–10 | Friday |
| 2022-03-25 | 5 from 1–50 | 2 from 1–12 | Friday |
| From 2022-03-29 | 5 from 1–50 | 2 from 1–12 | Tuesday and Friday |

Historical changes are corroborated by [WestLotto's Eurojackpot history](https://www.westlotto.de/newsroom/wissenswertes-eurojackpot/)
and [LOTTO.de's 2022 rule change](https://www.lotto.de/eurojackpot/produktaenderung-2022).

Completed annual archives must contain every scheduled draw. In the current
year, all scheduled draws through yesterday are required; today's draw may still
await publication. Unexpected pages, malformed rows, duplicates, future dates,
or incomplete years fail before the existing CSV is replaced. Future draw
results are never generated.

## CSV format and integrity checks

Files use UTF-8, commas, canonical `YYYY-MM-DD` dates, and one chronologically
sorted row per draw. Each number group is stored in ascending order. Main
numbers and Euro numbers/stars come from independent pools, so overlaps across
those pools are valid.

| Game | Exact header |
| --- | --- |
| Austrian Lotto | `date,n1,n2,n3,n4,n5,n6,zusatzzahl` |
| German Lotto | `date,n1,n2,n3,n4,n5,n6,superzahl` |
| EuroMillions | `date,n1,n2,n3,n4,n5,s1,s2` |
| Eurojackpot | `date,n1,n2,n3,n4,n5,e1,e2` |

German `superzahl` is required for every retained draw; `0` is valid. Its historical
introduction predates the archive's 2000 cutoff. Austrian `zusatzzahl` must differ from
the six main numbers. EuroMillions star limits are 9 initially, 11 from
**2011-05-10**, and 12 from **2016-09-27**.

```bash
# All four games, including freshness.
uv run --locked python scripts/check_integrity.py

# One game.
uv run --locked python scripts/check_integrity.py --game eurojackpot
uv run --locked python scripts/check_integrity.py --game euromillions

# Offline snapshot validation: skip only the time-dependent freshness check.
uv run --locked python scripts/check_integrity.py --skip-stale
```

`--game` accepts `at`, `de`, `eu`, `euromillions`, and `eurojackpot`. Legacy
`--country at|de|eu` still works; `eu` selects EuroMillions. Without a selector,
all four games are checked. Validation rejects incorrect headers/row widths,
invalid or future dates, pre-2000 Lotto records, duplicate dates/numbers,
unsorted values, missing required extras, and historical range violations.
German Lotto, EuroMillions, and Eurojackpot are also checked for internal
calendar gaps using their historical schedules. Freshness fails when the latest
stored result is more than seven days old.

Stored CSVs are read strictly before updates: malformed rows raise an actionable
error instead of silently disappearing during a rewrite. A temporary file is
fully written and flushed before atomic replacement. HTTP requests have
timeouts, close resources, preserve declared character encodings, and retry
transient failures with bounded backoff. Permanent errors are reported promptly.

## Sources and repaired data

| Game | Source |
| --- | --- |
| Austrian Lotto | [win2day](https://www.win2day.at/) annual `NN_W2D_STAT_Lotto_YYYY.csv` and historical CSVs referenced in the collector |
| German Lotto | [Lottozahlenonline annual archive](https://www.lottozahlenonline.de/statistik/beide-spieltage/lottozahlen-archiv.php) |
| EuroMillions | [win2day historical CSV](https://statics.win2day.at/media-nopagespeed/euromillionen-ergebnisse-2004-2017.csv) and annual `NN_W2D_STAT_EUML_YYYY.csv` |
| Eurojackpot | [Eurojackpot-Zahlen annual archive](https://www.eurojackpot-zahlen.eu/eurojackpot-zahlenarchiv.php) |

The supplied EuroMillions CSV had eleven missing dates and five incorrectly
dated rows. Independent [official FDJ archives](https://www.fdj.fr/jeux-de-tirage/euromillions-my-million/historique)
confirmed the repairs: all 1,193 compared records through 2019-02-26 agree on date
and numbers. The corrected archive has 1,982 draws and complete scheduled date
coverage from 2004-02-13 through 2026-09-18.

The importer now handles right-only historical blocks, Excel serial dates, and
six narrowly scoped upstream date corrections. Each correction requires both
the original date and all seven numbers to match, preventing the same source
from recreating known errors. One unsorted group in each of the AT and DE files
was normalized without changing the drawn numbers.

See [`docs/DATA_REPAIRS.md`](docs/DATA_REPAIRS.md) for all corrected rows, exact
reference downloads, and validation. The captured 2012 Eurojackpot fixture in
`tests/fixtures/` contains the source's draw container, retrieved on 2026-09-20,
and exercises the actual HTML date anomaly.

## GitHub Actions

External actions use verified current releases pinned to full commit SHAs.
The shared setup action installs Python and the dependencies from `uv.lock`.

| Workflow | Schedule or trigger | Purpose |
| --- | --- | --- |
| `update_at.yml` | Sun/Wed/Fri at 20:17 UTC | Austrian Lotto, including possible Friday bonus draws |
| `update_de.yml` | Wed/Sat at 20:37 UTC | German Lotto |
| `update_eu.yml` | Tue/Fri at 22:17 UTC | EuroMillions |
| `update_eurojackpot.yml` | Tue/Fri at 21:37 UTC | Eurojackpot |
| `_update_lottery.yml` | Called by the four collectors | Fetch, validate, commit, and push safely |
| `unit_tests.yml` | Push, pull request, or manual | Python 3.11–3.14 tests, data checks, page generation, package build |
| `deploy_pages.yml` | Successful default-branch tests/updates, or manual | Validate and publish the complete `public/` artifact |

Collector workflows also support manual runs with `init=true`. A shared writer
queue prevents overlapping pushes and preserves pending updates. Workflows
target the actual default branch; a manual feature-branch run does not write
the default branch. Push retries fetch/rebase and never force-push. Integrity
and freshness run even when no new result was found.

Repository setup:

1. Push this project, including `.github/`, `pyproject.toml`, and `uv.lock`, to the
   repository's default branch and enable GitHub Actions.
2. Permit the workflow token to write repository contents. If branch protection
   blocks these commits, configure an authorized GitHub App or adjust the rule.
3. Under **Settings → Pages → Build and deployment**, select **GitHub Actions**.
4. Run **Unit Tests** or **Deploy GitHub Pages** to initialize publication.

Updates use `GITHUB_TOKEN` by default. For an optional GitHub App, set repository
variable `APP_CLIENT_ID` and secret `APP_PRIVATE_KEY`, and install the app with
permission to write repository contents. Both values must refer to the same
app. The original hardcoded app identity has been removed.

Pages uses `workflow_run`, so deployment also follows commits made with
`GITHUB_TOKEN`. It validates the current default-branch revision and does not
check out untrusted pull-request revisions in its privileged path. Build and
deploy have separate permissions.

The existing Claude workflows remain optional. Enable them with repository
variable `ENABLE_CLAUDE=true` and secret `CLAUDE_CODE_OAUTH_TOKEN`. Trusted-author
checks, bounded runs, and restricted review behavior protect these workflows.
They are disabled by default and are not required for collection or publication.

## Dependencies and development

Direct packages verified on **2026-09-20**:

| Package | Pinned version |
| --- | --- |
| [requests](https://pypi.org/project/requests/) | 2.34.2 |
| [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) | 4.15.0 |
| [lxml](https://pypi.org/project/lxml/) | 6.1.3 |
| [setuptools](https://pypi.org/project/setuptools/) — build backend | 84.0.0 |

`uv.lock` also pins certifi, charset-normalizer, idna, soupsieve,
typing-extensions, and urllib3. Weekly Dependabot updates cover uv dependencies
and GitHub Actions. After reviewing new versions and updating exact constraints:

```bash
uv lock --upgrade
uv sync --locked
uv pip check
uv run --locked python -m unittest discover -s tests -v
uv run --locked python scripts/check_integrity.py --skip-stale
uv run --locked python scripts/generate_page.py
uv build
```

Tests are offline; HTTP behavior uses mocks and Git isolation tests use temporary
repositories. Live source imports are separate integration checks. See
[`docs/VALIDATION.md`](docs/VALIDATION.md) for the delivered snapshot's results and
action release references.

The generated page and CSVs can be hosted as static files. The project archives
published results and does not predict lottery outcomes. Source websites can
change their markup or correct results; a failed strict import reports the
problem without replacing the stored archive.
