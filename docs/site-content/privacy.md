# Privacy & data notice

*Last updated: 2026-11-19 (draft).*

OntoExplorer is a service of **Maastricht University**. This notice is a
**service-specific supplement** to the [UM General Privacy
Statement](https://www.maastrichtuniversity.nl/about-um/um-general-privacy-statement),
which governs how the University handles personal data; where this notice is
silent, the General Privacy Statement applies.

> **Review note (remove before publishing):** the facts below are drawn from the
> University's public privacy pages and from how the service actually processes
> data. A few items are marked *(verify)* where the exact wording/URL should be
> checked against the live UM page or confirmed by the GDPR Team / DPO. The
> operator should have this reviewed before it goes live.

## Who runs this service (data controller)

The data controller is **Maastricht University (UM)**. OntoExplorer is developed
and operated by UM's **Institute of Data Science (IDS)**.

For privacy questions or to exercise your rights, contact UM's **GDPR Team** at
**privacy@maastrichtuniversity.nl**, or the **Data Protection Officer** directly
at **fg@maastrichtuniversity.nl**. By post: *Maastricht University, attn. Data
Protection Officer, P.O. Box 616, 6200 MD Maastricht, The Netherlands*
*(verify the addressee — UM pages use both "Data Protection Officer" and "GDPR
Team UM" for this box)*. See also [Contact](contact.md).

## What we collect, and why

OntoExplorer is a catalogue of *ontologies*, not of people; we collect the
minimum personal data needed to run accounts and notify maintainers.

| Data | When | Why (purpose) |
|---|---|---|
| **Identity from your sign-in provider** — your provider (ORCID, GitHub, or email), your stable account id at that provider, your display name, and your verified email where the provider supplies it | When you sign in | To create and recognise your account, and to attribute the ontologies you submit |
| **Email address** | From your sign-in provider | To send you account- and submission-related notifications (see [When we email you](#when-we-email-you) below) — never marketing |
| **Account activity** — the ontologies you submit, own, or maintain; your API keys (stored only as a hash); your webhook subscriptions | As you use the service | To provide the submission, maintenance, and programmatic-access features |
| **Technical logs** — standard server logs, which may include IP address, request metadata, and timestamps | Automatically, on each request | To operate, secure, and debug the service |

**Legal basis.** We process this data to deliver a service you ask for (your
account and submissions) and in UM's legitimate interest in operating and securing
a research infrastructure. We do **not** sell personal data and do **not** use it
for advertising.

### How sign-in works (and a security note)

Sign-in is brokered by Keycloak across ORCID, GitHub, and email. Your
account is identified **only** by your provider plus your stable id at that
provider — **never** by email address. Accounts are deliberately **never merged by
email**, which prevents an account-takeover where someone signs in via a different
provider that happens to share your email.

### When we email you

We use your email address only for **transactional, account- and submission-related
messages** — never marketing, and we never share it for advertising. You receive an
email when:

- a version you submitted is **held for review** by the quality gate, with the
  specific reasons to correct;
- a submitted version's **OWL 2 profile could not be computed**;
- a **reminder** that one of your versions is still held awaiting correction;
- a long-held version is **set aside** after it has gone uncorrected for a while;
- your **uploader or maintainer request** is approved or declined.

Administrators additionally receive a notice when someone submits an uploader or
maintainer request, so the team can review it.

Detection of a **new upstream release** of an ontology is surfaced as an in-app
badge — it does **not** email you.

Email is sent on a best-effort basis from the platform's background workers. If your
sign-in provider supplied no email address, these notices appear in-app instead.
Sign-in **email verification** is handled by the identity broker (Keycloak) as part
of account setup.

## Public content

Ontologies submitted to OntoExplorer, and the artifacts computed from them, are
**public**. Your display name may appear as the attributed submitter/maintainer of
an ontology you add. Do not submit content you are not entitled to publish; each
ontology keeps its own upstream licence.

## Cookies & local storage

We use **essential** cookies/tokens to keep you signed in, and the browser's local
storage to remember interface preferences (such as a chosen filter or tab). These
are necessary for the site to function and are **not** used to track you across
other sites. The service uses **no third-party advertising or analytics
tracking** *(verify none has been added)*.

## Retention

- **Account data** — kept while your account is active; after you close your
  account it is deleted or anonymised within a reasonable period, except where a
  longer period is required by law *(confirm the exact period against UM's
  retention schedule)*.
- **Technical logs** — kept for a limited operational period, then deleted or
  aggregated *(confirm the exact period)*.
- **Public ontology content** persists as part of the catalogue; closing your
  account removes your personal attribution but does not withdraw the ontology
  from the public catalogue.

UM's retention periods are described in the [General Privacy
Statement](https://www.maastrichtuniversity.nl/about-um/um-general-privacy-statement).

## Your rights (GDPR)

If you are in the EU/EEA, you have the right to **access** your data, to
**rectify** it, to request **erasure**, to **restrict** or **object** to
processing, and to **data portability**.

**To exercise any right**, use UM's GDPR request form at
**https://www.maastrichtuniversity.nl/form-gdpr-request** *(verify URL)*, or email
**privacy@maastrichtuniversity.nl**. You may also contact the DPO at
**fg@maastrichtuniversity.nl**. *A dedicated in-app data-request shortcut is
planned; until it ships, requests are handled through these channels.*

You have the right to lodge a complaint with the Dutch supervisory authority, the
**Autoriteit Persoonsgegevens** (<https://www.autoriteitpersoonsgegevens.nl/en>).

## Hosting & processors

OntoExplorer is hosted on **Maastricht University / Institute of Data Science
infrastructure** in the Netherlands (EU). Processing involves:

- **Identity providers** — ORCID and GitHub (GitHub, Inc.) when you choose them to
  sign in, each under its own privacy policy and applicable international-transfer
  safeguards.
- **Email delivery** — ontology notifications are sent via UM's mail
  infrastructure *(confirm the mail provider/path)*.

## Changes

We may update this notice; material changes will be noted here with a new "last
updated" date.

---

## Items to confirm before publishing

Most details are now filled from UM's public pages. Please confirm the few marked
*(verify)* / *(confirm)* above:

- Exact postal addressee for the DPO box (DPO vs GDPR Team UM).
- Canonical URL of the UM General Privacy Statement and of the GDPR request form.
- That no analytics/non-essential cookies are in use.
- Retention periods for account data and technical logs (against UM's schedule).
- The mail provider/path used for notification emails.
- Whether UM Legal/DPO wants any wording changes for a university-operated service.
