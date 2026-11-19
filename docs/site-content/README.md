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

## Items to confirm

The legal/contact details are filled with a thoughtful first pass from Maastricht
University's public privacy pages: controller = **Maastricht University**, DPO
`fg@maastrichtuniversity.nl`, GDPR team `privacy@maastrichtuniversity.nl`,
supervisory authority **Autoriteit Persoonsgegevens**. A handful of items are
marked *(verify)* / *(confirm)* — exact statement/form URLs, the DPO postal
addressee, retention periods, the notification mail path, and the IDS URL.
The project contact email is **info-ids@maastrichtuniversity.nl**. Collected
lists are at the foot of `privacy.md` and `contact.md`.

## How to review

Edit the markdown directly (or leave inline comments on the PR). Once the copy is
settled, the second pass turns each file into a themed React page on the existing
router + nav, matching the app's look — no new content decisions at that point.
