# Changelog

All notable changes to Plainread are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this
project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html). Every release is
built by GitHub Actions; the build number shown in the app (`plainread --version`, the
web app footer and `/api/health`) is the Actions run number of that build.

## [Unreleased]

## [1.0.0] - 2026-11-06

First public release.

### Added

- **Photo, PDF or text in; plain-language explanation out.** Take a photo of a letter
  (or several pages), upload a PDF, or paste the text. Plainread reads it with
  Tesseract OCR and explains it in plain words.
- **Every important date**: deadlines, court dates, appointments, payment due dates,
  and when benefits or service end or change — with urgency ("Very soon", "This date
  has passed"), times, and deadlines worked out from periods such as "within 30 days
  of the date of this notice" (with a note saying how it was counted).
- **What to do, what happens if you do nothing, and your rights**, each as a short
  plain sentence. Lists in the letter ("Please bring: …") stay together.
- **Money, phone numbers, emails, websites and case/account numbers** pulled out,
  with tap-to-call links and copy buttons.
- **Proof for every claim**: each item carries the exact words from the letter, and
  "Show in letter" highlights them in the full text. Quotes are checked against the
  letter; anything that cannot be found is removed.
- **12 languages** for the results and the app: English, Spanish, Chinese
  (Simplified), Vietnamese, Tagalog, Korean, Russian, Arabic (right-to-left),
  Haitian Creole, French, Portuguese and Hindi.
- **Optional local AI** (Ollama or any OpenAI-compatible local server such as
  llama.cpp) for plainer wording and full translation. Plainread refuses to send
  letters to a non-local AI server unless explicitly allowed. The AI never adds
  dates, amounts or numbers.
- **"Words to know"** glossary of about 100 legal, medical, insurance and benefits
  terms in plain English and Spanish.
- **Read aloud** using only on-device voices, **add to calendar** (.ics with
  reminders 3 days and 1 day before), and **print**.
- Web app that works on phones and computers: large text, high contrast, dark mode,
  keyboard and screen-reader friendly, no external resources and a strict Content
  Security Policy.
- Command line: `plainread serve`, `plainread explain`, `plainread eval`,
  `plainread doctor`, `plainread languages`.
- Evaluation set of 22 fictional letters with hand-written answers, plus a separate
  held-out set; `plainread eval` scores text and photo (OCR) modes.
- Standalone apps for Windows, macOS and Linux, a Docker image with Tesseract, and a
  Python package.
- CI/CD: lint, type checks, tests on Python 3.10–3.14 and three operating systems,
  quality gates on the evaluation set, browser tests, Docker build, CodeQL, and
  tag-driven releases with build numbers, checksums and build provenance.

[Unreleased]: https://github.com/lobojoel2003/Plainread/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/lobojoel2003/Plainread/releases/tag/v1.0.0
