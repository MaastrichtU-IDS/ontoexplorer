import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import TermPage from './TermPage'

vi.mock('../hooks/useTerm', () => ({
  useTerm: () => ({
    data: {
      iri: 'http://purl.obolibrary.org/obo/GO_0008219',
      label: 'cell death',
      definition: 'A biological process involving cessation of metabolic processes.',
      entityType: 'class',
      synonyms: { exact: ['cell killing'], related: [], broad: [], narrow: [] },
      superclasses: ['http://purl.obolibrary.org/obo/GO_0008150'],
    },
    isLoading: false,
    error: null,
  }),
}))

vi.mock('../hooks/useClassTree', () => ({
  useClassTreeNodes: () => ({
    data: { terms: [{ iri: 'http://ex.org/A1', label: 'apoptosis' }] },
    isLoading: false,
  }),
}))

function wrap() {
  return render(
    <MemoryRouter initialEntries={['/browse/go/v1/term/http%3A%2F%2Fpurl.obolibrary.org%2Fobo%2FGO_0008219']}>
      <Routes>
        <Route path="/browse/:oid/:vid/term/*" element={<TermPage />} />
      </Routes>
    </MemoryRouter>
  )
}

test('shows label, definition, and synonyms', () => {
  wrap()
  expect(screen.getByRole('heading', { name: 'cell death' })).toBeInTheDocument()
  expect(screen.getByText(/biological process/i)).toBeInTheDocument()
  expect(screen.getByText('cell killing')).toBeInTheDocument()
})

test('shows subclasses', () => {
  wrap()
  expect(screen.getByText('apoptosis')).toBeInTheDocument()
})

test('shows superclasses', () => {
  wrap()
  expect(screen.getByText('GO_0008150')).toBeInTheDocument()
})

test('shows provenance', () => {
  wrap()
  expect(screen.getByText(/ontology:/i)).toBeInTheDocument()
})
