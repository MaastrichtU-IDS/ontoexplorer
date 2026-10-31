import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import EntityBrowser from './EntityBrowser'

const useEntities = vi.fn()
const useRelated = vi.fn()
const useFacets = vi.fn()

vi.mock('../hooks/useEntities', () => ({ useEntities: (p: unknown) => useEntities(p) }))
vi.mock('../hooks/useRelated', () => ({ useRelated: (p: unknown, e?: boolean) => useRelated(p, e) }))
vi.mock('../hooks/useFacets', () => ({ useFacets: (t: string) => useFacets(t) }))
vi.mock('../hooks/useDebounced', () => ({ useDebounced: <T,>(v: T) => v }))
vi.mock('../components/MOSQuery', () => ({ MOSQuery: () => <div data-testid="mos-query" /> }))
vi.mock('../lib/api', async (orig) => {
  const actual = await orig<typeof import('../lib/api')>()
  return { ...actual, api: { ...actual.api, stats: { public: () => Promise.resolve({ total_classes: 1234, total_individuals: 7 }) } } }
})

const row = (iri: string, label: string, ont = 'go', def = `def of ${label}`) => ({
  iri, primary_label: label, short: label, type: 'class', ontology_id: ont,
  ontology_title: ont.toUpperCase(), ontology_shortname: ont.toUpperCase(), version_id: 'v1', source: 'x', definition: def,
})

function LocationProbe() {
  const l = useLocation()
  return <div data-testid="loc">{l.search}</div>
}

function renderAt(url: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[url]}>
        <EntityBrowser />
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  useEntities.mockReset()
  useRelated.mockReset()
  useFacets.mockReset()
  useEntities.mockImplementation((p: { cursor?: string }) => {
    if (p.cursor === 'c1') {
      return { entities: [row('http://x/b', 'Beta')], isLoading: false, data: { next: null, approx_total: 2 } }
    }
    return { entities: [row('http://x/a', 'Alpha')], isLoading: false, data: { next: 'c1', approx_total: 2 } }
  })
  useRelated.mockReturnValue({ entities: [], unavailable: false, isLoading: false })
  useFacets.mockReturnValue({
    facets: [
      { ontology_id: 'go', short: 'GO', title: 'Gene Ontology', count: 5 },
      { ontology_id: 'uberon', short: 'UBERON', title: 'Uberon', count: 3 },
    ],
    isLoading: false,
  })
})

test('reads type from URL and tab switch updates URL, resetting facet/cursor/expanded', async () => {
  renderAt('/browse?type=individual')
  expect(useEntities.mock.calls.at(-1)![0]).toMatchObject({ type: 'individual' })
  await waitFor(() => expect(screen.getByRole('tab', { name: /Classes/ })).toHaveTextContent('1,234'))
  fireEvent.click(screen.getByLabelText(/GO/))
  fireEvent.click(screen.getByLabelText('Toggle definition'))
  fireEvent.click(screen.getByRole('button', { name: /Next/ }))
  fireEvent.click(screen.getByRole('tab', { name: /Classes/ }))
  expect(screen.getByTestId('loc')).toHaveTextContent('type=class')
  const last = useEntities.mock.calls.at(-1)![0]
  expect(last.type).toBe('class')
  expect(last.cursor).toBeUndefined()
  expect(last.ontology ?? []).toEqual([])
  expect(screen.queryByText('def of Alpha')).not.toBeInTheDocument()
})

test('empty query: keyset list with Next/Previous; last page disables Next', () => {
  renderAt('/browse')
  expect(screen.getByRole('link', { name: 'Alpha' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Previous/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /Next/ }))
  expect(screen.getByRole('link', { name: 'Beta' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Next/ })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: /Previous/ }))
  expect(screen.getByRole('link', { name: 'Alpha' })).toBeInTheDocument()
  expect(useRelated.mock.calls.at(-1)![1]).toBe(false)
})

test('non-empty query shows exact then Related by meaning; omitted when unavailable', () => {
  useRelated.mockReturnValue({ entities: [{ ...row('http://x/r', 'Gamma'), score: 0.9 }], unavailable: false, isLoading: false })
  const { unmount } = renderAt('/browse')
  fireEvent.change(screen.getByLabelText('Search'), { target: { value: '  alp ' } })
  expect(useEntities.mock.calls.at(-1)![0]).toMatchObject({ q: 'alp' })
  expect(useRelated.mock.calls.at(-1)![0]).toMatchObject({ q: 'alp' })
  expect(screen.getByText('Related by meaning')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Gamma' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Next/ })).not.toBeInTheDocument()
  unmount()
  useRelated.mockReturnValue({ entities: [], unavailable: true, isLoading: false })
  renderAt('/browse')
  fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'alp' } })
  expect(screen.queryByText('Related by meaning')).not.toBeInTheDocument()
})

test('related excludes IRIs already shown as exact matches', () => {
  useEntities.mockReturnValue({ entities: [row('http://x/a', 'Alpha')], isLoading: false, data: { next: null, approx_total: 1 } })
  useRelated.mockReturnValue({
    entities: [{ ...row('http://x/a', 'Alpha'), score: 0.99 }, { ...row('http://x/r', 'Gamma'), score: 0.9 }],
    unavailable: false, isLoading: false,
  })
  renderAt('/browse')
  fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'alp' } })
  expect(screen.getAllByRole('link', { name: 'Alpha' })).toHaveLength(1)
  expect(screen.getByRole('link', { name: 'Gamma' })).toBeInTheDocument()
})

test('definition caret toggles one row; global toggle flips all', () => {
  useEntities.mockReturnValue({
    entities: [row('http://x/a', 'Alpha'), row('http://x/b', 'Beta')], isLoading: false, data: { next: null, approx_total: 2 },
  })
  renderAt('/browse')
  expect(screen.queryByText('def of Alpha')).not.toBeInTheDocument()
  fireEvent.click(screen.getAllByLabelText('Toggle definition')[0])
  expect(screen.getByText('def of Alpha')).toBeInTheDocument()
  expect(screen.queryByText('def of Beta')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Show definitions' }))
  expect(screen.getByText('def of Beta')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Hide definitions' }))
  expect(screen.queryByText('def of Beta')).not.toBeInTheDocument()
})

test('facet search filters list; selecting an ontology narrows the query', () => {
  renderAt('/browse')
  fireEvent.change(screen.getByLabelText('Search ontologies'), { target: { value: 'uber' } })
  expect(screen.queryByLabelText(/GO/)).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText(/UBERON/))
  expect(useEntities.mock.calls.at(-1)![0]).toMatchObject({ ontology: ['uberon'] })
})

test('row links to the term page', () => {
  renderAt('/browse')
  const link = screen.getByRole('link', { name: 'Alpha' })
  expect(link).toHaveAttribute('href', '/ontologies/GO/v1?term=http%3A%2F%2Fx%2Fa')
})

test('row link does not depend on the facet list', () => {
  useFacets.mockReturnValue({ facets: [], isLoading: true })
  renderAt('/browse')
  expect(screen.getByRole('link', { name: 'Alpha' }))
    .toHaveAttribute('href', '/ontologies/GO/v1?term=http%3A%2F%2Fx%2Fa')
})

test('mode=query renders MOSQuery', () => {
  renderAt('/browse?mode=query')
  expect(screen.getByTestId('mos-query')).toBeInTheDocument()
  expect(screen.queryByLabelText('Search')).not.toBeInTheDocument()
})
