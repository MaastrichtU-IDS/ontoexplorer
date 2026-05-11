import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Search from './Search'

const mockResults = [
  { iri: 'http://ex.org/A', label: 'cell death', short: 'GO_0008219', match_type: 'entity' as const },
]

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [{ id: 'go', iri: 'http://go', status: 'indexed', created_at: '2024-01-01' }],
    isLoading: false,
  }),
}))

vi.mock('../hooks/useVersions', () => ({
  useVersions: () => ({
    data: { versions: [{ id: 'v1', ontology_id: 'go', version_iri: null, status: 'indexed', created_at: '2024-01-01' }] },
    isLoading: false,
  }),
}))

let mockSearchReturn: any = { data: null, isLoading: false, error: null }
vi.mock('../hooks/useSearch', () => ({
  useSearch: () => mockSearchReturn,
  useAutocomplete: () => ({ data: { completions: [] }, isLoading: false }),
  useGlobalSearch: () => ({ data: null, isLoading: false }),
}))

function wrap() {
  return render(<MemoryRouter><Search /></MemoryRouter>)
}

test('renders ontology selector and search controls', () => {
  wrap()
  expect(screen.getByRole('combobox')).toBeInTheDocument()
})

test('shows placeholder when no ontology selected', () => {
  wrap()
  expect(screen.getByText(/select an ontology to search within/i)).toBeInTheDocument()
})

test('shows search results when returned', () => {
  mockSearchReturn = { data: { mode: 'entity', results: mockResults, count: 1 }, isLoading: false, error: null }
  wrap()
  expect(screen.getByText('cell death')).toBeInTheDocument()
  expect(screen.getByText('GO_0008219')).toBeInTheDocument()
})

test('shows 503 error message when ontology not classified', () => {
  mockSearchReturn = { data: null, isLoading: false, error: { status: 503 } }
  wrap()
  expect(screen.getByText(/not yet classified/i)).toBeInTheDocument()
})
