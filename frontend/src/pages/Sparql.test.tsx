import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Sparql from './Sparql'

vi.mock('@triply/yasgui', () => ({
  default: vi.fn().mockImplementation(() => ({
    getTab: () => ({
      getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => 'SELECT * WHERE { ?s ?p ?o }') }),
      getYasr: () => ({ on: vi.fn() }),
      setEndpoint: vi.fn(),
      getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
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
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: vi.fn(),
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
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
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: vi.fn(),
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
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
  // The PREFIX-add path is suppressed (shortname already present), but the
  // scope-FROM sync still fires to inject FROM/FROM NAMED for the chip.
  // Verify: no call includes a duplicated PREFIX line; at least one call
  // includes the managed FROM clauses prepended to the original query.
  const calls = setValueMock.mock.calls.map(c => c[0] as string)
  for (const text of calls) {
    expect(text.match(/PREFIX pizza:/g) ?? []).toHaveLength(1)
  }
  expect(calls.some(t =>
    t.includes('FROM <urn:ontology:O1:V1>') &&
    t.includes('FROM NAMED <urn:ontology:O1:V1>')
  )).toBe(true)
})

it('navigates to the term page when an IRI cell is clicked', async () => {
  vi.resetModules()
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => '') }),
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: vi.fn(),
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
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
  const navigateMock = vi.fn()
  vi.doMock('react-router-dom', async () => {
    const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
    return { ...actual, useNavigate: () => navigateMock }
  })

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )

  const yasguiHost = screen.getByTestId('yasgui-container')
  const a = document.createElement('a')
  a.className = 'iri'
  a.href = 'https://w3id.org/ontostart/pizza/Margherita'
  a.textContent = 'Margherita'
  yasguiHost.appendChild(a)

  fireEvent.click(a)
  await waitFor(() => {
    expect(navigateMock).toHaveBeenCalledWith(
      '/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita'
    )
  })
})

it('runs two parallel fetches in Diff mode and renders DiffQueryView', async () => {
  vi.resetModules()

  const queryHandlers: Array<(req: any, cfg: any) => void> = []
  const fakeYasqe = {
    setValue: vi.fn(),
    getValue: vi.fn(() => 'SELECT ?x WHERE { ?x ?p ?o }'),
    on: vi.fn((evt: string, cb: any) => {
      if (evt === 'query') queryHandlers.push(cb)
    }),
  }
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => fakeYasqe,
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: vi.fn(),
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
      }),
      destroy: vi.fn(),
    })),
  }))

  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({
      ontologies: [
        { id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
          title: 'Pizza', created_at: '2024-01-01',
          latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } },
      ],
      isLoading: false,
    }),
  }))

  // Mock api.ontologies.versions for the toolbar
  vi.doMock('../lib/api', async () => {
    const actual = await vi.importActual<any>('../lib/api')
    return {
      ...actual,
      api: {
        ...actual.api,
        ontologies: {
          ...actual.api.ontologies,
          versions: vi.fn().mockResolvedValue({
            versions: [
              { id: 'V2', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: 'pizza-2.0', sha256: '', triple_count: 0, download_url: '', created_at: '2026-05-20' },
              { id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: 'pizza-1.0', sha256: '', triple_count: 0, download_url: '', created_at: '2024-01-01' },
            ],
          }),
        },
      },
    }
  })

  // Stub the global fetch to return two distinct binding sets for the two URLs
  global.fetch = vi.fn().mockImplementation(async (url: string) => {
    if (url.includes('urn%3Aontology%3AO1%3AV1')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          head: { vars: ['x'] },
          results: { bindings: [{ x: { type: 'uri', value: 'http://example.org/A' } }] },
        }),
      } as Response
    }
    if (url.includes('urn%3Aontology%3AO1%3AV2')) {
      return {
        ok: true, status: 200,
        json: async () => ({
          head: { vars: ['x'] },
          results: { bindings: [{ x: { type: 'uri', value: 'http://example.org/B' } }] },
        }),
      } as Response
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response
  }) as any

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )

  // Switch to Diff mode
  fireEvent.click(await screen.findByRole('button', { name: /^diff$/i }))

  // Wait for query handler to be subscribed and diff scope to settle
  await waitFor(() => expect(queryHandlers.length).toBeGreaterThan(0))

  // Also wait for the diff scope to be fully resolved (versions fetched + scope set)
  await waitFor(() => screen.getByText(/^From:/))

  // Give the version-fetch promise a moment to resolve and update diffScopeRef
  await waitFor(() => {
    // The scope is ready when we have a non-null diffScope which is indicated
    // by the From/To version selects being populated (not just "Pick version…" only)
    const selects = screen.getAllByRole('combobox')
    // At least one select should have an option beyond the placeholder
    return selects.some(s => s.querySelectorAll('option').length > 1)
  })

  // Fire Yasqe's query event manually
  queryHandlers[0]({ abort: vi.fn() }, { endpoint: '/api/v1/sparql/content' })

  // The two binding sets render as DiffQueryView's "Only From" and "Only To" rows
  await waitFor(() => {
    expect(screen.getByText('http://example.org/A')).toBeInTheDocument()
    expect(screen.getByText('http://example.org/B')).toBeInTheDocument()
  })
})

it('intercepts IRI clicks inside DiffQueryView and navigates in-app', async () => {
  vi.resetModules()
  const queryHandlers: Array<(req: any, cfg: any) => void> = []
  const fakeYasqe = {
    setValue: vi.fn(),
    getValue: vi.fn(() => 'SELECT ?x WHERE { ?x ?p ?o }'),
    on: vi.fn((evt: string, cb: any) => {
      if (evt === 'query') queryHandlers.push(cb)
    }),
  }
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => fakeYasqe,
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: vi.fn(),
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
      }),
      destroy: vi.fn(),
    })),
  }))
  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({
      ontologies: [
        { id: 'O1', iri: 'https://w3id.org/ontostart/pizza/', shortname: 'pizza',
          title: 'Pizza', created_at: '2024-01-01',
          latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } },
      ],
      isLoading: false,
    }),
  }))
  const navigateMock = vi.fn()
  vi.doMock('react-router-dom', async () => {
    const actual = await vi.importActual<any>('react-router-dom')
    return { ...actual, useNavigate: () => navigateMock }
  })
  vi.doMock('../lib/api', async () => {
    const actual = await vi.importActual<any>('../lib/api')
    return {
      ...actual,
      api: {
        ...actual.api,
        ontologies: {
          ...actual.api.ontologies,
          versions: vi.fn().mockResolvedValue({
            versions: [
              { id: 'V2', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: 'pizza-2.0', sha256: '', triple_count: 0, download_url: '', created_at: '2026-05-20' },
              { id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
                version_iri: 'pizza-1.0', sha256: '', triple_count: 0, download_url: '', created_at: '2024-01-01' },
            ],
          }),
        },
      },
    }
  })
  global.fetch = vi.fn().mockImplementation(async (_url: string) => {
    return {
      ok: true, status: 200,
      json: async () => ({
        head: { vars: ['x'] },
        results: { bindings: [{ x: { type: 'uri', value: 'https://w3id.org/ontostart/pizza/Margherita' } }] },
      }),
    } as Response
  }) as any

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )
  fireEvent.click(await screen.findByRole('button', { name: /^diff$/i }))
  await waitFor(() => expect(queryHandlers.length).toBeGreaterThan(0))
  queryHandlers[0]({ abort: vi.fn() }, { endpoint: '/api/v1/sparql/content' })

  const anchor = await screen.findByText('https://w3id.org/ontostart/pizza/Margherita')
  fireEvent.click(anchor)
  await waitFor(() => {
    expect(navigateMock).toHaveBeenCalledWith(
      '/ontologies/pizza?term=https%3A%2F%2Fw3id.org%2Fontostart%2Fpizza%2FMargherita'
    )
  })
})

it('fetches and applies labels when the labels toggle is enabled', async () => {
  vi.resetModules()
  const setEndpointMock = vi.fn()
  vi.doMock('@triply/yasgui', () => ({
    default: vi.fn().mockImplementation(() => ({
      getTab: () => ({
        getYasqe: () => ({ setValue: vi.fn(), getValue: vi.fn(() => '') }),
        getYasr: () => ({ on: vi.fn() }),
        setEndpoint: setEndpointMock,
        getRequestConfig: () => ({ endpoint: '/api/v1/sparql/content' }),
      }),
      destroy: vi.fn(),
    })),
  }))
  vi.doMock('../hooks/useOntologies', () => ({
    useOntologies: () => ({ ontologies: [], isLoading: false }),
  }))
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      results: { bindings: [
        { iri: { type: 'uri', value: 'http://a/' }, label: { type: 'literal', value: 'Alpha' } },
      ] },
    }),
  }) as any

  const { default: SparqlFresh } = await import('./Sparql')
  render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter><SparqlFresh /></MemoryRouter>
    </QueryClientProvider>,
  )

  const yasguiHost = screen.getByTestId('yasgui-container')
  const a = document.createElement('a')
  a.className = 'iri'
  a.href = 'http://a/'
  a.textContent = 'http://a/'
  yasguiHost.appendChild(a)

  fireEvent.click(screen.getByRole('button', { name: /toggle result labels/i }))

  await waitFor(() => {
    const span = yasguiHost.querySelector('.iri-label')
    expect(span).not.toBeNull()
    expect(span?.textContent).toBe(' · Alpha')
  })
})
