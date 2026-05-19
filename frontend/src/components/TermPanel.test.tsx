import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import TermPanel from './TermPanel'

const mockTerm = {
  iri: 'http://purl.obolibrary.org/obo/GO_0008219',
  label: 'cell death',
  definition: 'A biological process involving cessation of metabolic processes.',
  entityType: 'class' as const,
  isInverseTarget: false,
  typeOf: [],
  rawProperties: {},
  rawLabels: [],
  rawDefinitions: [],
  rawSynonyms: [],
  synonyms: { exact: ['cell killing'], related: [], broad: [], narrow: [] },
  superclasses: {
    asserted: [{ iri: 'http://purl.obolibrary.org/obo/GO_0008150', label: 'GO_0008150' }],
    inferred: [],
  },
  subclasses: {
    asserted: [{ iri: 'http://ex.org/A1', label: 'apoptosis' }],
    inferred: [],
  },
  superclassExpressions: [],
  inferredSuperclassExpressions: [],
  equivalentTo: [],
  disjointWith: [],
  inferredDisjointWith: [],
  disjointUnionOf: [],
  generalClassAxioms: [],
  domain: [],
  range: [],
  characteristics: [],
  inverseOf: [],
  usage: [],
  classUsage: [],
  schemaProperties: [],
  inheritedSchemaProperties: [],
}

vi.mock('../hooks/useTerm', () => ({
  useTerm: () => ({
    data: mockTerm,
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

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('shows term label and definition', () => {
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText('cell death')).toBeInTheDocument()
  expect(screen.getByText(/biological process/i)).toBeInTheDocument()
})

test('shows synonyms', () => {
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText(/cell killing/)).toBeInTheDocument()
})

test('shows open full page link', () => {
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText('Open full page ↗')).toBeInTheDocument()
})

test('shows superclasses', () => {
  // TermPanel renders Superclass section (no Subclasses section in the current
  // component). Assert the asserted superclass label is shown.
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText('GO_0008150')).toBeInTheDocument()
})
