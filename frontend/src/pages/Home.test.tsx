import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Home from './Home'

vi.mock('../hooks/useSearch', () => ({
  useGlobalSearch: () => ({ data: undefined }),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [{ id: 'go', iri: 'http://purl.obolibrary.org/obo/go.owl', created_at: '2024-01-01' }],
  }),
}))

vi.mock('../hooks/useVersions', () => ({
  useVersions: () => ({ data: undefined }),
}))

vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      stats: { public: () => Promise.resolve({
        total_ontologies: 5, total_classes: 1000,
        total_object_properties: 50, total_data_properties: 20,
        total_annotation_properties: 10, total_individuals: 30, total_axioms: 5000,
      }) },
      ontologies: {
        ...actual.api.ontologies,
        versions: () => Promise.resolve({ versions: [] }),
        search: () => Promise.resolve({ results: [], count: 0, truncated: false }),
      },
    },
  }
})

vi.mock('../components/OntologyPicker', () => ({
  default: () => <div data-testid="ontology-picker" />,
}))

vi.mock('../components/SearchBar', () => ({
  default: ({ onSearch }: { onSearch: (q: string) => void }) => (
    <input data-testid="search-bar" placeholder="search terms" onKeyDown={e => e.key === 'Enter' && onSearch('test')} />
  ),
}))

function renderHome() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Home />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders OntoExplorer heading', () => {
  renderHome()
  expect(screen.getByRole('heading', { name: /OntoExplorer/i })).toBeInTheDocument()
})

test('renders mode toggle buttons', () => {
  renderHome()
  expect(screen.getByText('Keyword Search')).toBeInTheDocument()
  expect(screen.getByText('Structured Query')).toBeInTheDocument()
})

test('switching to Structured Query tab shows search bar', () => {
  renderHome()
  fireEvent.click(screen.getByText('Structured Query'))
  expect(screen.getByTestId('search-bar')).toBeInTheDocument()
  expect(screen.getByTestId('ontology-picker')).toBeInTheDocument()
})

test('Classes stat card links to /browse?type=class', async () => {
  renderHome()
  const link = await screen.findByRole('link', { name: /Classes/i })
  expect(link).toHaveAttribute('href', '/browse?type=class')
})

test('Axioms stat card links to /browse in query mode', async () => {
  renderHome()
  const link = await screen.findByRole('link', { name: /Axioms/i })
  expect(link).toHaveAttribute('href', '/browse?mode=query')
})

test('Ontologies stat card still links to /ontologies', async () => {
  renderHome()
  const link = await screen.findByRole('link', { name: /Ontologies/i })
  expect(link).toHaveAttribute('href', '/ontologies')
})
