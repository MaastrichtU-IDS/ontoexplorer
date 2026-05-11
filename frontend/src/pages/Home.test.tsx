import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import Home from './Home'

vi.mock('../hooks/useSearch', () => ({
  useGlobalSearch: () => ({ data: undefined }),
}))

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [
      { id: 'go', iri: 'http://go', created_at: '2024-01-01' },
    ],
    isLoading: false,
  }),
}))

vi.mock('../components/OntologySelector', () => ({
  default: () => <select aria-label="ontology" />,
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
