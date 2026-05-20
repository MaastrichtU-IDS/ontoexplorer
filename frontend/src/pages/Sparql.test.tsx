import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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

it('prepends a PREFIX line when an ontology is added to scope', async () => {
  vi.resetModules()
  const setValueMock = vi.fn()
  const getValueMock = vi.fn(() => 'SELECT * WHERE { ?s ?p ?o }')
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: setValueMock, getValue: getValueMock }),
        setEndpoint: vi.fn(),
      }),
      destroy: vi.fn(),
    })),
  }))
  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({
      ontologies: [
        { id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
          title: 'Pizza', created_at: '2024-01-01',
          latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } },
      ],
      isLoading: false,
    }),
  }))

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
  fireEvent.click(screen.getByText('pizza'))

  await waitFor(() => {
    expect(setValueMock).toHaveBeenCalledWith(
      'PREFIX pizza: <https://w3id.org/ontostart/pizza/>\nSELECT * WHERE { ?s ?p ?o }'
    )
  })
})

it('does not duplicate PREFIX when the same shortname is already in the query', async () => {
  vi.resetModules()
  const setValueMock = vi.fn()
  const getValueMock = vi.fn(() => 'PREFIX pizza: <https://w3id.org/ontostart/pizza/>\nSELECT * WHERE { ?s ?p ?o }')
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: setValueMock, getValue: getValueMock }),
        setEndpoint: vi.fn(),
      }),
      destroy: vi.fn(),
    })),
  }))
  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({
      ontologies: [
        { id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
          title: 'Pizza', created_at: '2024-01-01',
          latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } },
      ],
      isLoading: false,
    }),
  }))

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )
  // Flush the mount-time setValue(DEFAULT_QUERY) call from the useEffect, then
  // clear so the assertion below is scoped only to click-triggered behaviour.
  await waitFor(() => expect(setValueMock).toHaveBeenCalled())
  setValueMock.mockClear()

  fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
  fireEvent.click(screen.getByText('pizza'))

  await new Promise(resolve => setTimeout(resolve, 50))
  expect(setValueMock).not.toHaveBeenCalled()
})
