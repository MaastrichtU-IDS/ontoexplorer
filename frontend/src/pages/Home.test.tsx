import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Home from './Home'

vi.mock('../hooks/useSearch', () => ({
  useGlobalSearch: () => ({ data: undefined }),
}))

vi.mock('../hooks/useOntologySearch', () => ({
  useOntologySearch: () => ({
    data: { ontologies: [{ id: 'go', iri: 'http://purl.obolibrary.org/obo/go.owl', created_at: '2024-01-01' }] },
    isLoading: false,
  }),
}))

vi.mock('../components/OntologyPicker', () => ({
  default: () => <div data-testid="ontology-picker" />,
}))

vi.mock('../components/SearchBar', () => ({
  default: ({ onSearch }: { onSearch: (q: string) => void }) => (
    <input placeholder="search terms" onKeyDown={e => e.key === 'Enter' && onSearch('test')} />
  ),
}))

test('renders Terms and Ontologies panel headings', () => {
  render(<MemoryRouter><Home /></MemoryRouter>)
  expect(screen.getByText('Terms')).toBeInTheDocument()
  expect(screen.getByText('Ontologies')).toBeInTheDocument()
})

test('shows ontology in ontologies panel', () => {
  render(<MemoryRouter><Home /></MemoryRouter>)
  expect(screen.getByText('go')).toBeInTheDocument()
})
