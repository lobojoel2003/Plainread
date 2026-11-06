# Contributing to Plainread

Thank you for helping. Plainread is used by people reading letters that can change
their lives, so we care most about two things: **never saying something the letter
does not say**, and **being easy to understand**.

## Set up

```bash
git clone https://github.com/lobojoel2003/Plainread.git
cd Plainread
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Install [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html) to work
on photo reading. Tests that need it are skipped when it is missing.

## Everyday commands

| Task | Command |
| --- | --- |
| Run the app | `plainread serve` |
| Explain a file | `plainread explain letter.jpg --lang es` |
| Lint and format | `ruff check src tests scripts` and `ruff format src tests scripts` |
| Type check | `mypy` |
| Tests | `pytest` (add `-m "not slow and not e2e"` to skip the OCR quality run) |
| Browser tests | `pip install -e ".[e2e]" && playwright install chromium && pytest -m e2e` |
| Quality report | `plainread eval --details` and `plainread eval --ocr` |
| Held-out report | `plainread eval --letters eval/holdout --details --no-fail` |

## How the code fits together

```
photo/PDF ──ocr.py──▶ text ──text.py──▶ sentences with offsets
                                   │
                    extract.py: dates, actions, consequences, rights,
                    money, contacts, ID numbers (rules, always on)
                                   │
                    pipeline.py: plain wording (plain.py), translation (i18n.py),
                    glossary, reading level, summary
                                   │
                    llm.py (optional, local only): rewrites and translates,
                    every new statement must quote the letter (grounding.py)
                                   │
                 api.py + web/ (browser app)        cli.py (terminal)
```

## Rules for changes

- **Every fact needs a quote.** New extractors must return the exact span of the
  letter they came from. `tests/test_quality.py` fails if any quote is not found.
- **Quality must not drop.** CI runs `plainread eval` in text and photo mode and
  fails below the thresholds in `src/plainread/evaluation.py`.
- **Do not tune on the held-out set.** `eval/holdout/` measures how well Plainread
  works on letters it was not built around. Add new tuning examples to
  `eval/letters/` instead.
- **Fictional data only.** Never commit a real letter. Use made-up names, `555-01xx`
  phone numbers and `.example` web addresses.
- **Plain language.** User-facing text should be short, friendly and readable at
  about a 5th-grade level.
- **Translations.** Add new user-facing strings to `src/plainread/locales/en.json`
  and every other locale file (`tests/test_i18n.py` checks they match).

## Versioning and releases

Plainread follows [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`.
The version lives in one place, `src/plainread/__init__.py`. Every build made by
GitHub Actions also gets a **build number** (the Actions run number) and the
**commit**, written into the package by `scripts/stamp_build.py`. They are shown by
`plainread --version`, in the web app footer and at `/api/health`.

To release:

1. Make sure `main` is green and `CHANGELOG.md` lists the changes under **Unreleased**.
2. Bump the version and roll the changelog:
   ```bash
   python scripts/bump_version.py patch   # or minor / major / 1.2.3
   ```
3. Commit, tag and push:
   ```bash
   git commit -am "Release v1.0.1"
   git tag -a v1.0.1 -m "Plainread 1.0.1"
   git push origin main --follow-tags
   ```
   Or, instead of pushing a tag, open **Actions → Release → Run workflow** on `main`
   and enter the tag (for example `v1.0.1`); the workflow creates the tag for you.
4. The **Release** workflow checks that the tag matches the version and the
   changelog, runs the full CI, builds the Python package, the Windows/macOS/Linux
   apps and the Docker image, and publishes a GitHub Release with notes, SHA-256
   checksums and signed build provenance.

Tags with a suffix, such as `v1.1.0-rc.1`, are published as pre-releases.
