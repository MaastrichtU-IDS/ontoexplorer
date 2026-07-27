import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import Browse from './Browse'

const CLASS_PAGE = {
  entities: [
    { iri: 'http://ex.org/Cell', label: 'cell', short: 'Cell', type: 'class', version_id: 'v1', ontology_id: 'o1', source: 'onto' },
  ],
  next: 'CURSOR2', approx_total: 3, limit: 50,
}
let mockEntities: any = { data: CLASS_PAGE, isFetching: false, isError: false }
const useEntitiesSpy = vi.fn((_p: any) => mockEntities)
vi.mock('../hooks/useEntities', () => ({ useEntities: (p: any) => useEntitiesSpy(p) }))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: [{ id: 'o1', iri: 'http://ex.org/onto', created_at: '2024-01-01' }] }),
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

test('query mode: renders the MOS query component', () => {
  renderAt('/browse?mode=query')
  expect(screen.getByTestId('mos-query')).toBeInTheDocument()
})

test('list mode empty state', () => {
  mockEntities = { data: { entities: [], next: null, approx_total: 0, limit: 50 }, isFetching: false, isError: false }
  renderAt('/browse?type=data_property')
  expect(screen.getByText(/No data properties in the repository yet/i)).toBeInTheDocument()
})
