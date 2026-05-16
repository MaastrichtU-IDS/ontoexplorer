import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sparql from './Sparql'

vi.mock('@triply/yasgui', () => ({
  default: vi.fn().mockImplementation(() => ({
    getTab: () => ({ getYasqe: () => ({ setValue: vi.fn() }) }),
    destroy: vi.fn(),
  })),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: vi.fn(),
}))

import { useOntologies } from '../hooks/useOntologies'

const ONTOLOGIES = [
  {
    id: 'abc1',
    iri: 'http://purl.obolibrary.org/obo/go.owl',
    shortname: 'go',
    title: 'Gene Ontology',
    created_at: '2024-01-01',
    latest_version: {
      id: 'v1', ontology_id: 'abc1', status: 'ready',
      format: 'owl', version_iri: null, sha256: '',
    },
  },
  {
    id: 'abc2',
    iri: 'http://purl.obolibrary.org/obo/mondo.owl',
    shortname: null,
    title: 'Mondo',
    created_at: '2024-01-01',
    latest_version: {
      id: 'v2', ontology_id: 'abc2', status: 'ready',
      format: 'owl', version_iri: null, sha256: '',
    },
  },
  {
    id: 'abc3',
    iri: 'http://example.org/pending.owl',
    shortname: 'pending-ont',
    title: 'Pending',
    created_at: '2024-01-01',
    latest_version: {
      id: 'v3', ontology_id: 'abc3', status: 'pending',
      format: 'owl', version_iri: null, sha256: '',
    },
  },
]

function wrap(ui: JSX.Element) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
    </MemoryRouter>
  )
}

beforeEach(() => {
  vi.mocked(useOntologies).mockReturnValue({ ontologies: ONTOLOGIES, isLoading: false })
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  })
})

test('shows Graphs toggle with count of ready ontologies, panel collapsed by default', () => {
  wrap(<Sparql />)
  // Only 2 ready ontologies (pending one excluded)
  expect(screen.getByRole('button', { name: /Graphs \(2\)/i })).toBeInTheDocument()
  expect(screen.queryByPlaceholderText('Filter ontologies…')).not.toBeInTheDocument()
})

test('clicking toggle expands panel showing filter input and ontology rows', () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  expect(screen.getByPlaceholderText('Filter ontologies…')).toBeInTheDocument()
  expect(screen.getByText('go')).toBeInTheDocument()      // shortname used
  expect(screen.getByText('mondo')).toBeInTheDocument()   // iri slug used (no shortname)
  expect(screen.queryByText('pending-ont')).not.toBeInTheDocument() // excluded (status pending)
})

test('filter input narrows rows by name', () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  fireEvent.change(screen.getByPlaceholderText('Filter ontologies…'), { target: { value: 'go' } })
  expect(screen.getByText('go')).toBeInTheDocument()
  expect(screen.queryByText('mondo')).not.toBeInTheDocument()
})

test('shows empty message when filter matches nothing', () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  fireEvent.change(screen.getByPlaceholderText('Filter ontologies…'), { target: { value: 'zzz' } })
  expect(screen.getByText('No matching ontologies')).toBeInTheDocument()
})

test('copy button writes correct graph URI to clipboard', async () => {
  wrap(<Sparql />)
  fireEvent.click(screen.getByRole('button', { name: /Graphs \(2\)/i }))
  const copyBtns = screen.getAllByRole('button', { name: 'Copy' })
  fireEvent.click(copyBtns[0])
  await waitFor(() => {
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('urn:ontology:abc1:v1')
  })
  expect(screen.getByText('✓')).toBeInTheDocument()
})
