# bioregistry upstream contributions

OntoExplorer resolves reused/external term IRIs to a canonical prefix via
[bioregistry](https://github.com/biopragmatics/bioregistry) (`iri_to_prefix` in
`ontoexplorer/modules/reuse/bioregistry.py`). For a handful of common
vocabularies bioregistry doesn't yet resolve our corpus's IRIs, we carry a
small local supplement (`_LOCAL_NS_PREFIX`). This file tracks the corresponding
**upstream contributions** so those entries become canonical for everyone — and
so we can delete each local row once its PR lands in a bioregistry release.

How bioregistry models these (verified against the installed registry):

- **Namespace variant of an existing vocabulary** → add the variant URI as a
  `providers` entry on the existing resource. `parse_iri` matches against every
  provider, so the variant then resolves to the canonical prefix. (Example in
  the registry: `ado` carries a `legacy` provider for its old Fraunhofer URL.)
- **Modular ontology network** → one prefix per module, each with `part_of` a
  parent resource — bioregistry does **not** collapse modules. (Example: the
  Allotrope Foundation Ontology is `allotrope.equipment`, `allotrope.process`,
  … each `part_of afo`; likewise `cath.superfamily part_of cath`.)

Our reuse **chip** shows the parent prefix (e.g. `arco`) regardless; the
per-module registration is only how bioregistry itself would model it.

## Entries to submit

Verify the exact existing prefix/namespace before opening each PR (some of these
prefixes already exist in bioregistry under a *different* canonical namespace —
then the fix is just adding our namespace as a `provider`, not a new resource).

| local prefix | namespace(s) we see | proposed bioregistry mechanism | status |
|---|---|---|---|
| `ecrm` | `http://erlangen-crm.org/current/` | new resource `ecrm` (Erlangen OWL-DL CRM), `has_canonical: cidoc.crm`, `uri_format: http://erlangen-crm.org/current/$1` | ☐ not submitted |
| `efrbroo` | `http://erlangen-crm.org/efrbroo/` | new resource `efrbroo` (Erlangen FRBRoo) | ☐ not submitted |
| `ssn` | `http://purl.oclc.org/NET/ssnx/ssn#` | add `provider` on existing `ssn` for the OCLC/ssnx namespace | ☐ not submitted |
| `qu` | `http://purl.oclc.org/NET/ssnx/qu/qu#` | new resource `qu` (SSN Quantity Kinds & Units) | ☐ not submitted |
| `dul` | `http://www.ontologydesignpatterns.org/ont/dul/DUL.owl#`, `http://www.loa-cnr.it/ontologies/DUL.owl#` | new/confirm `dul` (DOLCE+DnS Ultralite); register both namespaces (loa-cnr is the older location) as canonical + `provider` | ☐ not submitted |
| `iolite` | `http://www.ontologydesignpatterns.org/ont/dul/IOLite.owl#` | new resource `iolite` (Information Objects Lite), `part_of dul` | ☐ not submitted |
| `sp` | `http://spinrdf.org/sp#` | confirm vs existing `spin`; add `provider`/synonym for the `sp#` SPARQL-syntax namespace | ☐ not submitted |
| `gleif` | `https://www.gleif.org/ontology/Base/` | new resource `gleif` (GLEIF L1/Base) | ☐ not submitted |
| `lcc` | `https://www.omg.org/spec/LCC/Languages/LanguageRepresentation/`, `.../Countries/CountryRepresentation/` | new parent `lcc` (OMG Language & Country Codes) with per-module resources `part_of lcc` | ☐ not submitted |
| `arco` | `https://w3id.org/arco/ontology/<module>/` (core, location, catalogue, context-description, denotative-description, …) | parent `arco` + one resource per module, each `part_of arco` | ☐ not submitted |
| `italia` | `https://w3id.org/italia/onto/<module>/` (CLV, l0, …) | parent `italia` (OntoPiA / Italian gov) + per-module `part_of italia` | ☐ not submitted |

When a PR merges and ships in a bioregistry release we depend on, delete the
matching row from `_LOCAL_NS_PREFIX` and this table.
