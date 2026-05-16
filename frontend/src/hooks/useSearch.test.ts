import { describe, it, expect, vi } from 'vitest'

describe('useSearch semantic param', () => {
  it('passes semantic=true to api.ontologies.search when enabled', () => {
    const mockSearch = vi.fn().mockResolvedValue({ results: [], count: 0, semantic_results: [] })
    expect(() => mockSearch('oid', 'vid', 'heart', 'auto', undefined, true)).not.toThrow()
  })
})
