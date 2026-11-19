# Privacy & data notice

*Last updated: «DATE». This is a short notice describing what personal data
OntoExplorer processes and your rights over it. It is written to be expanded into
a fuller policy if required.*

> **Review note (remove before publishing):** this draft is grounded in how the
> service actually processes data, but the legal specifics in `«guillemets»` must
> be confirmed by the operator / Data Protection Officer before it goes live. A
> collected list is at the end.

## Who runs this service

OntoExplorer is operated by **«Maastricht University — Institute of Data Science
(IDS); confirm the controller's legal entity»** (the "data controller"). For any
privacy question or to exercise your rights, contact **«DPO / privacy contact,
e.g. privacy@…»**. See also [Contact](contact.md).

## What we collect, and why

OntoExplorer is a catalogue of *ontologies*, not of people; we collect the
minimum personal data needed to run accounts and notify maintainers.

| Data | When | Why (purpose) |
|---|---|---|
| **Identity from your sign-in provider** — your provider (ORCID, GitHub, Google, or email), your stable account id at that provider, your display name, and your verified email where the provider supplies it | When you sign in | To create and recognise your account, and to attribute the ontologies you submit |
| **Email address** | From your sign-in provider | To send you ontology-related notifications (for example, when a submission is held for review or an upstream update is detected) |
| **Account activity** — the ontologies you submit, own, or maintain; your API keys (stored only as a hash); your webhook subscriptions | As you use the service | To provide the submission, maintenance, and programmatic-access features |
| **Technical logs** — standard server logs, which may include IP address, request metadata, and timestamps | Automatically, on each request | To operate, secure, and debug the service |

We do **not** sell personal data, and we do **not** use it for advertising.
«Confirm whether any analytics or third-party tracking is used; if so, name it.»

### How sign-in works (and a security note)

Sign-in is brokered by Keycloak across ORCID, GitHub, Google, and email. Your
account is identified **only** by your provider plus your stable id at that
provider — **never** by email address. Accounts are deliberately **never merged by
email**, which prevents an account-takeover where someone signs in via a different
provider that happens to share your email.

## Public content

Ontologies submitted to OntoExplorer, and the artifacts computed from them, are
**public**. Your display name may appear as the attributed submitter/maintainer of
an ontology you add. Do not submit content you are not entitled to publish; each
ontology keeps its own upstream licence.

## Cookies & local storage

We use **essential** cookies/tokens to keep you signed in, and the browser's local
storage to remember interface preferences (such as a chosen filter or tab). These
are necessary for the site to function and are not used to track you across other
sites. «Confirm there are no non-essential/analytics cookies, or list them.»

## Retention

- **Account data** is kept while your account is active and for **«retention
  period»** afterwards, then deleted or anonymised.
- **Technical logs** are kept for **«log retention period»**.
- **Public ontology content** persists as part of the catalogue; see erasure
  below for what happens to attribution if you close your account.

## Your rights (GDPR)

If you are in the EU/EEA, you have the right to **access** your data, to
**rectify** it, to request **erasure**, to **restrict** or **object** to
processing, and to **data portability**. You also have the right to lodge a
complaint with a supervisory authority («the relevant DPA, e.g. the Dutch
*Autoriteit Persoonsgegevens*»).

**To exercise any right**, email **«DPO / privacy contact»** (or use the request
route on the [Contact](contact.md) page). We will respond within the period
required by law. *Note: a dedicated in-app data-request form is planned; until it
ships, requests are handled by email.*

## Hosting & processors

OntoExplorer is hosted by **«hosting / infrastructure, e.g. Maastricht University
IDS infrastructure»**. Sign-in relies on the identity providers you choose (ORCID,
GitHub, Google) under their own privacy policies. «List any other sub-processors
(email delivery, etc.).»

## Changes

We may update this notice; material changes will be noted here with a new "last
updated" date.

---

## Placeholders to confirm before publishing

- `«DATE»` — the effective date.
- Controller legal entity (and address, if required).
- DPO / privacy contact email.
- Whether any analytics or third-party tracking is in use.
- Whether any non-essential cookies exist.
- Retention periods — account data, technical logs.
- Hosting / infrastructure provider and any sub-processors (e.g. email delivery).
- The relevant supervisory authority to name.
- Whether an institutional (university) privacy statement should be linked as the
  governing policy, with this as the service-specific supplement.
