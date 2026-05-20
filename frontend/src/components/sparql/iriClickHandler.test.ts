import { describe, it, expect, vi, beforeEach } from 'vitest'
import { installIriClickHandler } from './iriClickHandler'
import type { Ontology } from '../../lib/api'

vi.mock('../../lib/api', () => ({
  api: { globalSearch: { search: vi.fn() } },
}))
import { api } from '../../lib/api'
const mockSearch = api.globalSearch.search as ReturnType<typeof vi.fn>

const PIZZA: Ontology = {
  id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
  title: 'Pizza', created_at: '2024-01-01',
  latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
} as any

beforeEach(() => {
  document.body.innerHTML = ''
  mockSearch.mockReset()
})

function makeAnchor(href: string): { root: HTMLElement; anchor: HTMLAnchorElement } {
  const root = document.createElement('div')
  root.innerHTML = `<a class="iri" href="${href}">${href}</a>`
  document.body.appendChild(root)
  return { root, anchor: root.querySelector('a')! }
}

function dispatchClick(target: HTMLElement, opts: Partial<MouseEventInit> = {}) {
  const ev = new MouseEvent('click', { bubbles: true, cancelable: true, ...opts })
  target.dispatchEvent(ev)
  return ev
}

describe('installIriClickHandler', () => {
  it('navigates to the term page when the IRI is in scope', () => {
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('https://w3id.org/ontostart/pizza/Margherita')
    installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    const ev = dispatchClick(anchor)
    expect(navigate).toHaveBeenCalledWith(
      '/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita'
    )
    expect(ev.defaultPrevented).toBe(true)
  })

  it('does not navigate on modified clicks (ctrlKey)', () => {
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('https://w3id.org/ontostart/pizza/Margherita')
    installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    const ev = dispatchClick(anchor, { ctrlKey: true })
    expect(navigate).not.toHaveBeenCalled()
    expect(ev.defaultPrevented).toBe(false)
  })

  it('falls back to /api/v1/search when no scope ontology matches and navigates on result', async () => {
    mockSearch.mockResolvedValue({
      results: [{ iri: 'http://outside/Foo', ontology_id: 'O1', label: 'Foo', short: 'Foo', type: 'class', version_id: 'V1' }],
      count: 1, truncated: false,
    })
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('http://outside/Foo')
    installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    const ev = dispatchClick(anchor)
    // preventDefault fires synchronously
    expect(ev.defaultPrevented).toBe(true)
    // navigate happens after the fetch resolves
    await new Promise(r => setTimeout(r, 0))
    expect(mockSearch).toHaveBeenCalledWith('http://outside/Foo', 1)
    expect(navigate).toHaveBeenCalledWith(
      '/ontologies/pizza?term=http%3A%2F%2Foutside%2FFoo'
    )
  })

  it('opens raw IRI in new tab when search returns empty', async () => {
    mockSearch.mockResolvedValue({ results: [], count: 0, truncated: false })
    const navigate = vi.fn()
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { root, anchor } = makeAnchor('http://nothing/Foo')
    installIriClickHandler(root, { getOntologies: () => [], navigate })
    dispatchClick(anchor)
    await new Promise(r => setTimeout(r, 0))
    expect(navigate).not.toHaveBeenCalled()
    expect(openSpy).toHaveBeenCalledWith('http://nothing/Foo', '_blank')
    openSpy.mockRestore()
  })

  it('opens raw IRI when fetch rejects', async () => {
    mockSearch.mockRejectedValue(new Error('boom'))
    const navigate = vi.fn()
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const { root, anchor } = makeAnchor('http://nothing/Foo')
    installIriClickHandler(root, { getOntologies: () => [], navigate })
    dispatchClick(anchor)
    await new Promise(r => setTimeout(r, 0))
    expect(openSpy).toHaveBeenCalledWith('http://nothing/Foo', '_blank')
    openSpy.mockRestore()
  })

  it('teardown removes the listener', () => {
    const navigate = vi.fn()
    const { root, anchor } = makeAnchor('https://w3id.org/ontostart/pizza/Foo')
    const teardown = installIriClickHandler(root, { getOntologies: () => [PIZZA], navigate })
    teardown()
    dispatchClick(anchor)
    expect(navigate).not.toHaveBeenCalled()
  })
})
