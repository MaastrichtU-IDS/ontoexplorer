import { describe, it, expect } from 'vitest'
import { qRank } from './Dashboard'
import type { Ontology } from '../lib/api'

function o(partial: Partial<Ontology>): Ontology {
  return { id: 'x', iri: 'http://x/o', shortname: null, title: null, created_at: '2026-01-01', ...partial } as Ontology
}

describe('dashboard search relevance (qRank)', () => {
  it('tiers exact shortname → prefix → substring → title → else', () => {
    expect(qRank(o({ shortname: 'pro', title: 'Protein' }), 'pro')).toBe(0)
    expect(qRank(o({ shortname: 'property', title: 'x' }), 'pro')).toBe(1)
    expect(qRank(o({ shortname: 'improb', title: 'x' }), 'pro')).toBe(2)
    expect(qRank(o({ shortname: 'zzz', title: 'A process ontology' }), 'pro')).toBe(3)
    expect(qRank(o({ shortname: 'zzz', title: 'Gene Ontology' }), 'pro')).toBe(4)
  })

  it('is case-insensitive and falls back to label when title is blank', () => {
    expect(qRank(o({ shortname: 'PRO' }), 'pro')).toBe(0)
    expect(qRank(o({ shortname: 'zzz', title: null, label: 'A process' } as Partial<Ontology>), 'pro')).toBe(3)
  })

  it('floats an exact shortname match ahead of alphabetically-earlier matches', () => {
    const rows = [
      o({ shortname: 'anatomy-pro', title: 'A' }),   // substring (tier 2)
      o({ shortname: 'pro', title: 'Protein' }),      // exact (tier 0)
      o({ shortname: 'property', title: 'B' }),        // prefix (tier 1)
    ]
    // Alphabetical first (as the dashboard's name sort would leave it)…
    rows.sort((a, b) => (a.shortname ?? '').localeCompare(b.shortname ?? ''))
    // …then stable relevance sort, mirroring the component.
    const ranked = [...rows].sort((a, b) => qRank(a, 'pro') - qRank(b, 'pro'))
    expect(ranked.map(r => r.shortname)).toEqual(['pro', 'property', 'anatomy-pro'])
  })
})
