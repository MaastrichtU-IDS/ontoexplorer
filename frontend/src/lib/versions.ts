// Version-aware ordering for ontology versions, mirroring the backend's
// `_version_key` (modules/search/versions.py): rank by the integer groups in
// `version_iri` (so 1.62 > 1.61 > 1.34.0, and 2024-05-01 > 2024-01-01), with
// `created_at` only as a tiebreaker. Dropdowns and version lists must use THIS,
// not `created_at`, or a later-ingested OLDER snapshot sorts above a newer
// release (the SIO 1.34.0-vs-1.62 bug).
import type { OntologyVersion } from './api'

const NOT_READY = ['pending', 'failed', 'deprecated']

export function versionNums(v: OntologyVersion): number[] {
  const m = (v.version_iri ?? '').match(/\d+/g)
  return m ? m.map(Number) : []
}

// Human-readable label for a version dropdown / list. The old Dashboard helper
// took the last path segment of version_iri, so a versionless IRI like
// `…/sio-release.owl` rendered as the uninformative "sio-release.owl". Instead:
// prefer a parsed version token (date or dotted) from version_iri, else fall back
// to the ingest date, and always disambiguate with the date + triple count (so
// same-IRI versions differ), suffixing status / "current".
export function versionLabel(
  v: OntologyVersion,
  opts: { isDefault?: boolean } = {},
): string {
  const seg = v.version_iri
    ? (v.version_iri.replace(/[/#]+$/, '').split(/[/#]/).pop() ?? '')
    : ''
  const token = seg.match(/\d{4}-\d{2}-\d{2}/)?.[0] ?? seg.match(/\d+(?:\.\d+)+/)?.[0] ?? ''

  const date = v.created_at
    ? new Date(v.created_at).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
    : ''
  const primary = token || date || v.id.slice(0, 8)

  const parts: string[] = [primary]
  if (token && date) parts.push(date)   // show the date too when the token is a version
  if (typeof v.triple_count === 'number') parts.push(`${v.triple_count.toLocaleString()} triples`)
  if (opts.isDefault) parts.push('current')
  else if (v.status && v.status !== 'ready') parts.push(v.status)
  return parts.join(' · ')
}

// Compare two integer-group tuples like Python tuple comparison, where a missing
// element counts as lower (so (1,61) < (1,61,0)). Returns <0 if a<b, >0 if a>b.
function cmpNums(a: number[], b: number[]): number {
  const n = Math.max(a.length, b.length)
  for (let i = 0; i < n; i++) {
    const d = (a[i] ?? -1) - (b[i] ?? -1)
    if (d !== 0) return d
  }
  return 0
}

// Sort comparator: highest version first (newest release), created_at desc as a
// tiebreaker. Use as `versions.slice().sort(compareVersionsDesc)`.
export function compareVersionsDesc(a: OntologyVersion, b: OntologyVersion): number {
  const c = cmpNums(versionNums(b), versionNums(a))
  if (c !== 0) return c
  return (b.created_at ?? '').localeCompare(a.created_at ?? '')
}

// The ready version immediately preceding `currentId` by VERSION order — the
// highest version_iri strictly less than it. Matches the backend's
// version_predecessor, so "diff vs predecessor" and the default From selection
// use the real previous release, not whatever was ingested last.
export function versionPredecessor(
  versions: OntologyVersion[], currentId: string,
): OntologyVersion | undefined {
  const cur = versions.find(v => v.id === currentId)
  if (!cur) return undefined
  const curNums = versionNums(cur)
  const earlier = versions.filter(
    v => v.id !== currentId && !NOT_READY.includes(v.status) && cmpNums(versionNums(v), curNums) < 0,
  )
  if (earlier.length === 0) return undefined
  return earlier.slice().sort(compareVersionsDesc)[0]
}
