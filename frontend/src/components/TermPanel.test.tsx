import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import TermPanel from './TermPanel'

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

test('shows term label and definition', () => {
  render(
    <MemoryRouter>
      <TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" />
    </MemoryRouter>
  )
  expect(screen.getByText('cell death')).toBeInTheDocument()
  expect(screen.getByText(/biological process/i)).toBeInTheDocument()
})

test('shows synonyms', () => {
  render(
    <MemoryRouter>
      <TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" />
    </MemoryRouter>
  )
  expect(screen.getByText('cell killing')).toBeInTheDocument()
})

test('shows open full page link', () => {
  render(
    <MemoryRouter>
      <TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" />
    </MemoryRouter>
  )
  expect(screen.getByText('Open full page ↗')).toBeInTheDocument()
})

test('shows subclasses', () => {
  render(
    <MemoryRouter>
      <TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" />
    </MemoryRouter>
  )
  expect(screen.getByText(/apoptosis/i)).toBeInTheDocument()
})
