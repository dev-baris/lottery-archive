# Validation and release record

Verified on **2026-09-20** for project version **1.2.0**.

## Test results

| Python | Tests | Result |
| --- | ---: | --- |
| 3.11.16 | 346 | Passed |
| 3.12.14 | 346 | Passed |
| 3.13.15 | 346 | Passed |
| 3.14.7 | 346 | Passed |

The four runs use the verified current dependency versions. Python 3.11, 3.13, and 3.14 use isolated environments originally installed from `uv.lock`; Python 3.12 uses the same package versions through an editable pip installation. Version 1.2.0 was installed successfully with `uv sync --locked --offline` on Python 3.14. The refreshed lock passed `uv lock --check --offline`, dependency compatibility checks passed, and the version 1.2.0 source/wheel build succeeded. The tests are offline; live checks are recorded separately below. This script-based project is distributed as the complete project ZIP, including its collectors, data, and workflows.

The original supplied suite had 157 passing tests; version 1.1.0 had 310. Version 1.2.0 adds 36 regression tests covering the inclusive 2000 cutoff, initialization and recovery bounds, rejection of out-of-scope CSV reads/writes without replacing the original file, German Superzahl requirements, Germany's historical draw calendar, and rejection of pre-2000 data before public page generation. Previous coverage for source formats, Eurojackpot, historical number limits, HTTP handling, Git commits, and the combined updater remains in the full suite.

## Version 1.2.0 source and data checks

- Removed **814 Austrian** and **2,307 German** records dated before 2000. Compared each retained row, field by field, with the version 1.1.0 project ZIP: **zero changed dates or numbers**. Both European CSVs are byte-identical to version 1.1.0.
- Reparsed the two previously downloaded official Austrian historical files through the updated strict parser: **1,114** retained draws from 2000-01-02 through 2010-09-05 and **764** from 2010-09-08 through 2017-12-31. All **1,878** records match the current archive exactly; all pre-2000 source sections are excluded.
- Fetched Germany's year 2000 from the live combined archive and compared all **57 records** with the retained CSV: **zero mismatches**. The source covers 53 Saturdays plus four December Wednesdays. [LOTTO Bayern's archive description](https://www.lotto-bayern.de/lotto6aus49/gewinnzahlen) and [game history](https://www.lotto-bayern.de/lotto6aus49/normalschein) document the separate Wednesday lottery's integration on 2000-12-06. The checker validates this historical calendar and detects internal gaps.
- Ran the regular AT and DE collectors against their live 2025 and 2026 source pages/files. Both returned **zero new draws**, and the stored CSVs remained byte-identical.
- All four final CSVs passed structural, rule, ordering, duplicate, and freshness checks. German Lotto, EuroMillions, and Eurojackpot also passed their internal scheduled-date checks.
- Regenerated the public page: all four download CSVs are byte-identical to their canonical files, and both Lotto links explicitly say their history starts in 2000. The page generator rejects an older Lotto row even when the last row is current, before publishing any output.

## Retained version 1.1.0 source verification

The following checks were performed during the preceding update on the same
date. Their repaired European data remains unchanged in version 1.2.0; they are
recorded here as prior evidence, not additional full imports for this release.

- Imported every Eurojackpot annual archive from 2012 to 2026 through the supplied URLs: **991 draws**, from **2012-03-23** to **2026-09-18**. All completed years are complete; 2026 contains the 75 draws published through September 18.
- Ran the combined updater successfully against all four live sources. AT, EuroMillions, and Eurojackpot had no new rows. Germany added the draw on **2026-09-19**.
- The regular Eurojackpot update returned no changes after the full import, confirming idempotency against the live source.
- Compared **1,072** strictly parsed win2day historical EuroMillions draws against the repaired archive: **zero mismatches**.
- Compared both official Austrian historical files, originally containing **1,928** and **764** draws (2,692 total), against the version 1.1.0 archive: **zero mismatches**. Those original counts include 814 pre-2000 draws removed in version 1.2.0. Narrow handling preserves legitimate cancellation/postponement notices with empty number fields.
- Independently compared **1,193** official FDJ historical records against the repaired EuroMillions archive: every date and number agrees. See [DATA_REPAIRS.md](DATA_REPAIRS.md) for the evidence and exact corrections.

| Eurojackpot year | Draws |
| --- | ---: |
| 2012 | 41 |
| 2013 | 52 |
| 2014 | 52 |
| 2015 | 52 |
| 2016 | 53 |
| 2017 | 52 |
| 2018 | 52 |
| 2019 | 52 |
| 2020 | 52 |
| 2021 | 53 |
| 2022 | 92 |
| 2023 | 104 |
| 2024 | 105 |
| 2025 | 104 |
| 2026 | 75 |

## Final archive fingerprints

| CSV | Records | First archived draw | Latest draw | SHA-256 |
| --- | ---: | --- | --- | --- |
| `at/lotto_6aus45/results.csv` | 2,868 | 2000-01-02 | 2026-09-18 | `a91dd0a67f18006e9405a506b1a96e97d863d0a97399dc6ebc1ee1549e3d3809` |
| `de/lotto_6aus49/results.csv` | 2,741 | 2000-01-01 | 2026-09-19 | `e89a343a325732854f9827ca6e3c2a80fc3a9e361a49188cc42524aaea6f43d9` |
| `eu/euromillions/results.csv` | 1,982 | 2004-02-13 | 2026-09-18 | `624460c6c03887842f8c95bdd54f6e784a96b3992794a55be6a55e8e0be91e9d` |
| `eu/eurojackpot/results.csv` | 991 | 2012-03-23 | 2026-09-18 | `a97479573a48a0a4a3b91f66ca41468faca81bc7e8638abc884c09ba7acf12ba` |

## Workflow validation

Action/dependency pins and push behavior were verified in version 1.1.0 and are
retained. Version 1.2.0 updates the AT/DE manual import descriptions to start at
2000; actionlint and public artifact checks were rerun after those changes.

- Every external action is pinned to a verified full commit SHA; action inputs were compared with each pinned upstream `action.yml`.
- All 11 workflow/action/Dependabot YAML files parse correctly.
- **actionlint 1.7.12** passed with local reusable/composite actions resolved, excluding only its unsupported `concurrency.queue` diagnostic. GitHub [officially documents `queue: max`](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency); that linter release predates the field.
- Ran the reusable workflow's push-step shell against disposable Git repositories: concurrent changes to another file survive rebase/push; reruns become no-ops; same-file conflicts fail without replacing remote history.
- An independent workflow/dependency review found no further concrete defects.
- Generated the public page and checked that all four relative download links resolve to byte-identical copies of their canonical CSVs.

**Execution boundary:** hosted GitHub Actions jobs and GitHub Pages publication were not run against a live repository. Enable Actions, allow the configured token/app to write, and select the Actions source for Pages as described in the README. Local package installation, tests, live collector calls, generated files, and Git simulations were executed.

## Verified action releases

| Action | Release | Pinned commit |
| --- | --- | --- |
| `actions/checkout` | [v7.0.1](https://github.com/actions/checkout/releases/tag/v7.0.1) | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| `actions/configure-pages` | [v6.0.0](https://github.com/actions/configure-pages/releases/tag/v6.0.0) | `45bfe0192ca1faeb007ade9deae92b16b8254a0d` |
| `actions/create-github-app-token` | [v3.2.0](https://github.com/actions/create-github-app-token/releases/tag/v3.2.0) | `bcd2ba49218906704ab6c1aa796996da409d3eb1` |
| `actions/deploy-pages` | [v5.0.1](https://github.com/actions/deploy-pages/releases/tag/v5.0.1) | `368f82528645a54fb793d4d04e342629a3f51346` |
| `actions/setup-python` | [v7.0.0](https://github.com/actions/setup-python/releases/tag/v7.0.0) | `5fda3b95a4ea91299a34e894583c3862153e4b97` |
| `actions/upload-pages-artifact` | [v5.0.0](https://github.com/actions/upload-pages-artifact/releases/tag/v5.0.0) | `fc324d3547104276b827a68afc52ff2a11cc49c9` |
| `anthropics/claude-code-action` | [v1.0.231](https://github.com/anthropics/claude-code-action/releases/tag/v1.0.231) | `cfc3eb22bfed5c26ef66e3223c982af27e4524de` |
| `astral-sh/setup-uv` | [v10.1.0](https://github.com/astral-sh/setup-uv/releases/tag/v10.1.0) | `bec219d24cd3e171d82865faccec33120bb574f4` |

## Verified Python and build dependencies

| Package | Version |
| --- | --- |
| [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) | 4.15.0 |
| [requests](https://pypi.org/project/requests/) | 2.34.2 |
| [lxml](https://pypi.org/project/lxml/) | 6.1.3 |
| [uv](https://pypi.org/project/uv/) | 0.12.17 |
| [certifi](https://pypi.org/project/certifi/) | 2026.7.22 |
| [idna](https://pypi.org/project/idna/) | 3.20 |
| [soupsieve](https://pypi.org/project/soupsieve/) | 2.9.2 |
| [typing-extensions](https://pypi.org/project/typing-extensions/) | 4.16.0 |
| [urllib3](https://pypi.org/project/urllib3/) | 2.8.0 |
| [setuptools](https://pypi.org/project/setuptools/) | 84.0.0 |
| [charset-normalizer](https://pypi.org/project/charset-normalizer/) | 3.5.1 |

Direct constraints live in `pyproject.toml`; exact runtime/transitive versions and distribution hashes live in `uv.lock`. CI pins uv itself, and the build backend is pinned separately. Weekly Dependabot updates cover the dependency lock and GitHub Action references.
