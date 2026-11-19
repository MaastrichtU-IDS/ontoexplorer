# OntoExplorer site content

The four public information pages — **About**, **Documentation**, **Privacy**, and
**Contact** — are live in the app and rendered from markdown.

**Live source (edit here):** [`frontend/src/content/`](../../frontend/src/content/)

| File | Route | Page |
|---|---|---|
| `about.md` | `/about` | What OntoExplorer is + feature overview |
| `documentation.md` | `/docs` | Detailed documentation on every feature |
| `privacy.md` | `/privacy` | Privacy & data notice (GDPR-aware) |
| `contact.md` | `/contact` | GitHub issues, email, team, data requests |

The pages are rendered by `frontend/src/components/MarkdownPage.tsx`
(react-markdown + remark-gfm + rehype-slug), which themes the prose, wires the
in-document table of contents and cross-page links into SPA navigation, and fills
`{{nOnt}}` on the About page with the live catalogue count. To change copy, edit the
markdown under `frontend/src/content/` and ship a frontend release.

## Still worth a human confirm on the Privacy/Contact pages

The legal details were filled from Maastricht University's public privacy pages
(controller = Maastricht University; DPO `fg@maastrichtuniversity.nl`; GDPR Team
`privacy@maastrichtuniversity.nl`; supervisory authority Autoriteit
Persoonsgegevens). Before wide promotion, have UM Legal / the DPO confirm:

- the exact UM General Privacy Statement and GDPR-request-form URLs,
- the DPO postal addressee,
- retention periods and the notification mail path,
- that no analytics / non-essential cookies are in use,
- the IDS institute URL on the Contact page.
