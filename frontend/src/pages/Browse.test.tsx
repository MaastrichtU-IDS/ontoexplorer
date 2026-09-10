import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Browse from './Browse'

const CLASS_PAGE = {
  entities: [
    { iri: 'http://ex.org/Cell', label: 'cell', short: 'Cell', type: 'class', source: 'onto',
      ontologies: [{ ontology_id: 'o1', version_id: 'v1' }] },
  ],
  next: 'CURSOR2', approx_total: 3, limit: 50,
}
// A term reused across two ontologies (collapsed row).
const SHARED_COLLAPSED = {
  entities: [
    { iri: 'http://shared/Term', label: 'shared', short: 'Term', type: 'class', source: '',
      ontologies: [{ ontology_id: 'o1', version_id: 'v1' }, { ontology_id: 'o2', version_id: 'v2' }] },
  ],
  next: null, approx_total: 1, limit: 50,
}
let mockEntities: any = { data: CLASS_PAGE, isFetching: false, isError: false }
const useEntitiesSpy = vi.fn((_p: any) => mockEntities)
vi.mock('../hooks/useEntities', () => ({ useEntities: (p: any) => useEntitiesSpy(p) }))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: [
    { id: 'o1', iri: 'http://ex.org/onto', shortname: 'onto', created_at: '2024-01-01' },
    { id: 'o2', iri: 'http://ex.org/pizza', shortname: 'pizza', created_at: '2024-01-01' },
  ] }),
}))

vi.mock('./Home', () => ({ MOSQuery: () => <div data-testid="mos-query" /> }))

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/browse" element={<Browse />} /></Routes>
    </MemoryRouter>
  )
}

test('list mode: renders an entity row linking to its term page', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  renderAt('/browse?type=class')
  const link = screen.getByRole('link', { name: /cell/i })
  expect(link).toHaveAttribute('href', expect.stringContaining('term=http%3A%2F%2Fex.org%2FCell'))
})

test('list mode: Next advances using the returned cursor', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  useEntitiesSpy.mockClear()
  renderAt('/browse?type=class')
  fireEvent.click(screen.getByRole('button', { name: /Next/i }))
  const calls = useEntitiesSpy.mock.calls
  const lastCall = calls[calls.length - 1][0]
  expect(lastCall.cursor).toBe('CURSOR2')
})

test('list mode: switching type tab resets the cursor', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  useEntitiesSpy.mockClear()
  renderAt('/browse?type=class')
  fireEvent.click(screen.getByRole('button', { name: /Next/i }))  // cursor now CURSOR2
  fireEvent.click(screen.getByRole('button', { name: 'Object Properties' }))
  const calls = useEntitiesSpy.mock.calls
  const lastCall = calls[calls.length - 1][0]
  expect(lastCall.type).toBe('object_property')
  expect(lastCall.cursor ?? null).toBeNull()
})

test('list mode: Next is disabled while fetching', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: true, isError: false }
  renderAt('/browse?type=class')
  expect(screen.getByRole('button', { name: /Next/i })).toBeDisabled()
})

test('query mode: renders the MOS query component', () => {
  renderAt('/browse?mode=query')
  expect(screen.getByTestId('mos-query')).toBeInTheDocument()
})

test('list mode empty state', () => {
  mockEntities = { data: { entities: [], next: null, approx_total: 0, limit: 50 }, isFetching: false, isError: false }
  renderAt('/browse?type=data_property')
  expect(screen.getByText(/No data properties in the repository yet/i)).toBeInTheDocument()
})

test('defining ontology badge is highlighted and sorted before reusers', () => {
  // term IRI lives under o1's namespace (http://ex.org/onto) -> o1 defines it,
  // o2 (pizza) reuses it. o2 is listed first to prove the sort reorders it.
  mockEntities = { data: {
    entities: [
      { iri: 'http://ex.org/onto/Foo', label: 'foo', short: 'Foo', type: 'class', source: '',
        ontologies: [{ ontology_id: 'o2', version_id: 'v2' }, { ontology_id: 'o1', version_id: 'v1' }] },
    ], next: null, approx_total: 1, limit: 50,
  }, isFetching: false, isError: false }
  renderAt('/browse?type=class')
  const def = screen.getByTitle(/Defines this term/i)
  const reuse = screen.getByTitle(/Reuses this term/i)
  expect(def).toHaveTextContent('onto')
  expect(reuse).toHaveTextContent('pizza')
  // definer appears before the reuser in the DOM (sorted first)
  expect(def.compareDocumentPosition(reuse) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
})

test('collapsed row renders one clickable badge per ontology', () => {
  mockEntities = { data: SHARED_COLLAPSED, isFetching: false, isError: false }
  renderAt('/browse?type=class')
  const onto = screen.getByRole('link', { name: 'onto' })
  const pizza = screen.getByRole('link', { name: 'pizza' })
  expect(onto).toHaveAttribute('href', expect.stringContaining('term=http%3A%2F%2Fshared%2FTerm'))
  expect(onto.getAttribute('href')).toContain('/v1?')
  expect(pizza.getAttribute('href')).toContain('/v2?')
})

test('typing in the search box queries with q and hides the pager', async () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  useEntitiesSpy.mockClear()
  renderAt('/browse?type=class')
  fireEvent.change(screen.getByLabelText('Search entities'), { target: { value: 'cell' } })
  await waitFor(() => {
    const calls = useEntitiesSpy.mock.calls
    expect(calls[calls.length - 1][0].q).toBe('cell')
  })
  // search returns a single ranked page -> no Next/Previous pager
  expect(screen.queryByRole('button', { name: /Next/i })).not.toBeInTheDocument()
})

test('collapse toggle requests collapsed listing', () => {
  mockEntities = { data: CLASS_PAGE, isFetching: false, isError: false }
  useEntitiesSpy.mockClear()
  renderAt('/browse?type=class')
  fireEvent.click(screen.getByLabelText(/Collapse duplicates/i))
  const calls = useEntitiesSpy.mock.calls
  expect(calls[calls.length - 1][0].collapse).toBe(true)
})
