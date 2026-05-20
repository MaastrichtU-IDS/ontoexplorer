import { describe, it, expect, vi, beforeEach } from 'vitest'
import { buildOntoCompleter } from './ontoCompleter'
import type { Ontology } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: {
    globalSearch: {
      autocomplete: vi.fn(),
    },
  },
}))

import { api } from '../../lib/api'
const mockAutocomplete = api.globalSearch.autocomplete as ReturnType<typeof vi.fn>

const PIZZA: Ontology = {
  id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
  title: 'Pizza', created_at: '2024-01-01',
  latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
} as any

function stubYasqe(tokenString: string, prefixes: Record<string, string> = {}) {
  return {
    getCompleteToken: () => ({ string: tokenString, type: null }),
    getPrefixesFromQuery: () => prefixes,
  } as any
}

beforeEach(() => {
  mockAutocomplete.mockReset()
})

describe('buildOntoCompleter — isValidCompletionPosition', () => {
  const completer = buildOntoCompleter(() => [], () => [])

  it('returns true inside <...>', () => {
    expect(completer.isValidCompletionPosition(stubYasqe('<http://example.org/Marg'))).toBe(true)
  })

  it('returns true for a CURIE-like token', () => {
    expect(completer.isValidCompletionPosition(stubYasqe('pizza:Marg'))).toBe(true)
  })

  it('returns false for a variable', () => {
    expect(completer.isValidCompletionPosition(stubYasqe('?x'))).toBe(false)
  })

  it('returns false for an empty token', () => {
    expect(completer.isValidCompletionPosition(stubYasqe(''))).toBe(false)
  })
})

describe('buildOntoCompleter — get', () => {
  it('fetches with the IRI partial when inside <...>', async () => {
    mockAutocomplete.mockResolvedValue({
      completions: [{ text: 'Pizza', iri: 'https://w3id.org/ontostart/pizza/Pizza', type: 'class',
                     short: 'Pizza', insert: 'Pizza', lang: 'en', cross_language: false,
                     ontology_shortname: 'pizza' }],
      context: 'name', replace_from: 0, replace_to: 4,
    })
    const completer = buildOntoCompleter(() => ['O1'], () => [PIZZA])
    const result = await completer.get(stubYasqe('<Marg'), { string: '<Marg', type: null } as any)
    expect(mockAutocomplete).toHaveBeenCalledWith('Marg', -1, ['O1'])
    expect(result).toEqual(['<https://w3id.org/ontostart/pizza/Pizza>'])
  })

  it('fetches with the local-name partial and filters by matching ontology for a known CURIE', async () => {
    mockAutocomplete.mockResolvedValue({
      completions: [{ text: 'Margherita', iri: 'https://w3id.org/ontostart/pizza/Margherita', type: 'class',
                     short: 'Margherita', insert: 'Margherita', lang: 'en', cross_language: false,
                     ontology_shortname: 'pizza' }],
      context: 'name', replace_from: 0, replace_to: 10,
    })
    const completer = buildOntoCompleter(() => ['O1', 'O2'], () => [PIZZA])
    const result = await completer.get(
      stubYasqe('pizza:Marg', { pizza: 'https://w3id.org/ontostart/pizza/' }),
      { string: 'pizza:Marg', type: 'string-2' } as any,
    )
    expect(mockAutocomplete).toHaveBeenCalledWith('Marg', -1, ['O1'])
    expect(result).toEqual(['pizza:Margherita'])
  })

  it('falls back to fleet-wide when CURIE prefix is unbound in the editor', async () => {
    mockAutocomplete.mockResolvedValue({ completions: [], context: 'name', replace_from: 0, replace_to: 0 })
    const completer = buildOntoCompleter(() => ['O1'], () => [PIZZA])
    await completer.get(
      stubYasqe('unknown:Foo'),
      { string: 'unknown:Foo', type: 'string-2' } as any,
    )
    expect(mockAutocomplete).toHaveBeenCalledWith('Foo', -1, [])
  })

  it('passes empty ontology_ids when scope selection is empty', async () => {
    mockAutocomplete.mockResolvedValue({ completions: [], context: 'name', replace_from: 0, replace_to: 0 })
    const completer = buildOntoCompleter(() => [], () => [PIZZA])
    await completer.get(stubYasqe('<Marg'), { string: '<Marg', type: null } as any)
    expect(mockAutocomplete).toHaveBeenCalledWith('Marg', -1, [])
  })

  it('returns an empty list on fetch error', async () => {
    mockAutocomplete.mockRejectedValue(new Error('boom'))
    const completer = buildOntoCompleter(() => [], () => [])
    const result = await completer.get(stubYasqe('<x'), { string: '<x', type: null } as any)
    expect(result).toEqual([])
  })
})
