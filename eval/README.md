# Plainread evaluation set

A set of **fictional** sample letters with hand-written correct answers. It is how
we measure whether Plainread finds every deadline, amount, phone number and
action in a letter — and whether it invents anything.

Run it with:

```bash
plainread eval                 # text mode: reads the .txt letters
plainread eval --ocr           # OCR mode: renders each letter to an image first
plainread eval --json report.json
```

CI runs both modes on every push and fails if quality drops below the
thresholds in `.github/workflows/ci.yml`.

## Files

Each letter is two files in `eval/letters/`:

| File | What it holds |
| --- | --- |
| `<id>.txt` | The letter text, exactly as a person would see it on paper (letterhead, body, footer). |
| `<id>.json` | The correct answers ("gold labels") for that letter. |

All people, organisations, addresses, phone numbers (`555-01xx`), emails and
websites (`.example` domains) are made up.

## Answer format (`<id>.json`)

```json
{
  "id": "court-small-claims",
  "description": "Small claims court summons with a hearing date",
  "letter_type": "court",
  "today": "2026-03-02",
  "letter_date": "2026-02-24",
  "sender": "Lakemont County",
  "dates": [
    {"date": "2026-03-20", "kind": "hearing"},
    {"date": "2026-03-16", "kind": "respond_by", "relative": true}
  ],
  "amounts": [1250.00],
  "phones": ["5550142"],
  "emails": ["clerk@lakemontcourts.example"],
  "websites": ["lakemontcourts.example/selfhelp"],
  "references": ["SC-2026-004512"],
  "actions": [["appear", "court"], ["bring", "receipts"]],
  "consequences": [["default", "judgment"]],
  "rights": [["interpreter"]]
}
```

| Field | Meaning |
| --- | --- |
| `letter_type` | One of `court`, `housing`, `medical_bill`, `health_insurance`, `insurance`, `benefits`, `tax`, `utility`, `debt`, `immigration`, `school`, `employment`, `medical`, `general`. |
| `today` | The "current date" used when scoring (so urgency is reproducible). Usually a few days after `letter_date`. |
| `letter_date` | The date the letter was written or mailed, or `null` if the letter has none. |
| `sender` | A short substring that must appear in the detected sender name. |
| `dates` | **Every** date the reader needs to know about: deadlines to respond, return, pay or appeal; appointments; hearings; dates when benefits, coverage or service end or change. Leave out the letter's own date, dates of birth, past dates (dates of service, "we received your form on…") and dates before the letter date. |
| `dates[].kind` | `respond_by`, `hearing`, `appointment`, `payment_due`, `ends`, `starts` or `other`. |
| `dates[].relative` | `true` when the letter gives a period instead of a date ("within 30 days of the date of this notice"). The date is then `letter_date + N` calendar days (or N business days, Monday–Friday, when the letter says "business days"). If the period starts when the reader *receives* or is *served* the letter, still count from `letter_date` — the safest choice. |
| `amounts` | Every distinct money amount in the letter, as numbers. |
| `phones` | Every phone, fax or TTY number, digits only, without a leading country code `1`. |
| `emails`, `websites` | Every email address and website, lowercase, without `https://` or `www.`. |
| `references` | Case, claim, account, member, notice, invoice, policy and similar ID numbers, exactly as printed. |
| `actions` | One entry per thing the reader must or should do. Each entry is a list of lowercase keywords that all appear in the sentence that asks for the action. |
| `consequences` | Same format, for sentences that say what happens if the reader does nothing. |
| `rights` | Same format, for sentences about the reader's rights or free help (appeal, interpreter, free legal aid…). |

## Scoring

* **Dates, amounts, phones, emails, websites, references** — precision, recall
  and F1 against the gold list (exact match after normalisation).
* **Date kinds** — share of correctly found dates whose `kind` is also right.
* **Actions, consequences, rights** — recall: an entry counts as found when one
  extracted item's quote contains all of its keywords.
* **Letter type** — accuracy.
* **Grounding** — share of all extracted items whose quote is found word for
  word in the letter. This must be 100%.
