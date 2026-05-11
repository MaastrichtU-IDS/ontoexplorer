import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Browse from './Browse'

const mockVersions = [{ id: 'v1', ontology_id: 'go', version_iri: null, status: 'indexed', created_at: '2024-01-01' }]

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [{ id: 'go', iri: 'http://go', status: 'indexed', created_at: '2024-01-01' }],
    isLoading: false,
  }),
}))

vi.mock('../hooks/useVersions', () => ({
  useVersions: () => ({ data: { versions: mockVersions }, isLoading: false }),
}))

vi.mock('../hooks/useClassTree', () => ({
  useClassTreeNodes: () => ({
    data: { terms: [{ iri: 'http://ex.org/A', label: 'Term A' }] },
    isLoading: false,
  }),
}))

vi.mock('../hooks/useTerm', () => ({
  useTerm: () => ({
    data: {
      iri: 'http://ex.org/A',
      label: 'Term A',
      definition: 'A test term.',
      entityType: 'class',
      synonyms: { exact: [], related: [], broad: [], narrow: [] },
      superclasses: [],
    },
    isLoading: false,
    error: null,
  }),
}))

function wrap(path = '/browse') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/browse" element={<Browse />} />
        <Route path="/browse/:oid/:vid" element={<Browse />} />
      </Routes>
    </MemoryRouter>
  )
}

test('shows ontology list on load', () => {
  wrap()
  expect(screen.getByText('go')).toBeInTheDocument()
})

test('shows class tree when oid and vid are in url', () => {
  wrap('/browse/go/v1')
  expect(screen.getByText('Term A')).toBeInTheDocument()
})

test('shows placeholder when no ontology selected', () => {
  wrap('/browse')
  expect(screen.getByText('Select an ontology from the left')).toBeInTheDocument()
})

test('clicking ontology navigates to browse/:oid/:vid', () => {
  wrap('/browse')
  fireEvent.click(screen.getByText('go'))
  expect(screen.getByText('Term A')).toBeInTheDocument()
})
