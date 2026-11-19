# OntoExplorer site content — review drafts

These are **draft copy** for four public pages, written for review and editing
before we wire the approved text into the frontend (`frontend/src/pages/…`) in a
second pass. Nothing here is live yet.

| File | Becomes | Status |
|---|---|---|
| [`about.md`](about.md) | `/about` — what OntoExplorer is + feature overview | draft |
| [`documentation.md`](documentation.md) | `/docs` — detailed documentation on every feature | draft |
| [`privacy.md`](privacy.md) | `/privacy` — minimal privacy & data notice (GDPR-aware) | draft, **needs legal review** |
| [`contact.md`](contact.md) | `/contact` — GitHub issues, email, team, data requests | draft |

## Placeholders to confirm

Text in `«guillemets»` is a value I could not invent and you must confirm. The
privacy notice carries most of them (controller legal entity, DPO contact,
retention periods, hosting/sub-processors, analytics). A collected list is at the
bottom of `privacy.md`.

## How to review

Edit the markdown directly (or leave inline comments on the PR). Once the copy is
settled, the second pass turns each file into a themed React page on the existing
router + nav, matching the app's look — no new content decisions at that point.
