import { describe, it, expect } from 'vitest'
import { versionLabel } from './versions'
import type { OntologyVersion } from './api'

function v(extra: Partial<OntologyVersion>): OntologyVersion {
  return {
    id: 'v', version_iri: 'https://w3id.org/ontostart/pro/1.0.2',
    status: 'needs_review', triple_count: 120,
    created_at: '2026-11-13T15:24:29Z', ...extra,
  } as unknown as OntologyVersion
}

describe('versionLabel', () => {
  it('distinguishes two same-day versions of the same version_iri (shows the time)', () => {
    // The bug this guards: re-ingests created two 1.0.2 versions on the same day;
    // a date-only label made them identical so you could not tell which to delete.
    const older = versionLabel(v({ id: 'a', created_at: '2026-11-13T15:24:29Z' }))
    const newer = versionLabel(v({ id: 'b', created_at: '2026-11-13T16:01:06Z' }))
    expect(older).not.toEqual(newer)
  })

  it('keeps the version token and triple count in the label', () => {
    const label = versionLabel(v({}))
    expect(label).toContain('1.0.2')
    expect(label).toContain('120 triples')
    expect(label).toContain('needs_review')
  })

  it('does not render "Invalid Date" when created_at is missing', () => {
    const label = versionLabel(v({ created_at: undefined }))
    expect(label).not.toMatch(/Invalid Date/)
  })
})
