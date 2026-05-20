import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sparql from './Sparql'

vi.mock('@triply/yasgui', () => ({
  default: vi.fn().mockImplementation(() => ({
    getTab: () => ({
      getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => 'SELECT * WHERE { ?s ?p ?o }') }),
      setEndpoint: vi.fn(),
    }),
    destroy: vi.fn(),
  })),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: vi.fn(),
}))

vi.mock('../components/QuerySidebar', () => ({
  default: () => null,
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
      triple_count: null, download_url: '', created_at: '2024-01-01',
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
      triple_count: null, download_url: '', created_at: '2024-01-01',
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
      triple_count: null, download_url: '', created_at: '2024-01-01',
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

it('renders the ScopeToolbar', async () => {
  wrap(<Sparql />)
  expect(await screen.findByText(/No scope selected/i)).toBeInTheDocument()
})
