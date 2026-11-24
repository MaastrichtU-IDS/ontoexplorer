import { render, screen, fireEvent, within, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Home from '../Home'
import FederatedResults from '../../components/FederatedResults'
import { api, type FederatedBlock } from '../../lib/api'

vi.mock('../../hooks/useSearch', () => ({ useGlobalSearch: () => ({ data: undefined }) }))
vi.mock('../../hooks/useOntologies', () => ({ useOntologies: () => ({ ontologies: [] }) }))
vi.mock('../../hooks/useVersions', () => ({ useVersions: () => ({ data: undefined }) }))
vi.mock('../../components/OntologyPicker', () => ({ default: () => <div /> }))

const BLOCK: FederatedBlock = {
  catalogues: [
    { id: 'agro', label: 'AgroPortal', status: 'ok', count: 1, took_ms: 120 },
    { id: 'oe2', label: 'OntoExplorer B', status: 'empty', count: 0, took_ms: 80 },
    { id: 'slow', label: 'Slow Portal', status: 'timeout', count: 0, took_ms: 2000 },
  ],
  results: [
    {
      iri: 'http://example.org/crop', acronym: 'CROP', title: 'Crop Ontology',
      description: 'd', publisher: null, license: null, homepage: null,
      source_landing_url: 'http://agroportal.example/ontologies/CROP',
      source: { id: 'agro', label: 'AgroPortal' }, remote: true,
    },
  ],
}

describe('api.ontologies.list federated opt', () => {
  const urls: string[] = []
  beforeEach(() => {
    urls.length = 0
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      urls.push(String(url))
      return new Response(JSON.stringify({ ontologies: [], offset: 0, limit: 50, total: 0 }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }))
  })
  afterEach(() => vi.unstubAllGlobals())

  const listUrl = () => urls.find(u => u.includes('/ontologies?'))!

  test('sends federated=true when set in opts', async () => {
    await api.ontologies.list(0, 50, 'crop', undefined, undefined, undefined, false, undefined, 'list', { federated: true })
    expect(listUrl()).toContain('federated=true')
  })

  test('omits federated when not set', async () => {
    await api.ontologies.list(0, 50, 'crop', undefined, undefined, undefined, false, undefined, 'list')
    expect(listUrl()).not.toContain('federated')
  })
})

describe('FederatedResults', () => {
  test('renders a badged outbound link per remote row plus the responded line', () => {
    render(<FederatedResults federated={BLOCK} />)
    expect(screen.getByRole('heading', { name: /Also found in other catalogues/i })).toBeInTheDocument()
    const link = screen.getByRole('link', { name: /Crop Ontology/i })
    expect(link).toHaveAttribute('href', 'http://agroportal.example/ontologies/CROP')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    expect(link).toHaveAttribute('rel', expect.stringContaining('noreferrer'))
    expect(within(link).getByText('AgroPortal')).toBeInTheDocument()
    expect(within(link).getByText('CROP')).toBeInTheDocument()
    expect(screen.getByText(/2 of 3 catalogues responded/i)).toBeInTheDocument()
  })

  test('renders nothing when federated block is absent', () => {
    const { container } = render(<FederatedResults federated={undefined} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('Home federation toggle', () => {
  function renderHome() {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={qc}>
        <MemoryRouter><Home /></MemoryRouter>
      </QueryClientProvider>
    )
  }

  test('toggle off does not send federated; on sends it and shows the section', async () => {
    const spy = vi.spyOn(api.ontologies, 'list').mockResolvedValue({
      ontologies: [], offset: 0, limit: 50, total: 0, federated: BLOCK,
    } as never)
    renderHome()
    const search = screen.getByPlaceholderText(/Search ontologies by name/i)
    fireEvent.change(search, { target: { value: 'crop' } })
    await waitFor(() => expect(spy).toHaveBeenCalled())
    expect(spy.mock.calls.every(c => !(c[9] as { federated?: boolean } | undefined)?.federated)).toBe(true)

    fireEvent.click(screen.getByLabelText(/Include federated catalogues/i))
    await waitFor(() =>
      expect(spy.mock.calls.some(c => (c[9] as { federated?: boolean } | undefined)?.federated === true)).toBe(true)
    )
    expect(await screen.findByText(/Also found in other catalogues/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Crop Ontology/i })).toHaveAttribute('target', '_blank')
    spy.mockRestore()
  })
})
