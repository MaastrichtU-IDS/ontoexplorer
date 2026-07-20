import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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
  propertyLabels: {},
  rawLabels: [],
  rawDefinitions: [],
  rawElucidations: [],
  rawSynonyms: [],
  synonyms: { exact: ['cell killing'], related: [], broad: [], narrow: [] },
  superclasses: {
    asserted: [{ iri: 'http://purl.obolibrary.org/obo/GO_0008150', label: 'GO_0008150' }],
    inferred: [] as { iri: string; label: string }[],
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

// A variant with one inferred (reasoner-derived) superclass, so the
// "inference" explain toggle renders — used by the justification/
// capability-disable tests below.
const mockTermWithInferredSuper = {
  ...mockTerm,
  superclasses: {
    asserted: mockTerm.superclasses.asserted,
    inferred: [{ iri: 'http://ex.org/Inferred1', label: 'inferred superclass' }],
  },
}

// Reassigned per-test so different specs can exercise different term shapes
// without re-declaring the whole hook mock. Vitest hoists `vi.mock` factories
// above other module-scope code, but allows referencing identifiers prefixed
// with "mock" (as the pre-existing `mockTerm` already relied on) — reading
// this variable at call time (inside the arrow function body) picks up
// whatever a given test assigned before rendering.
let mockCurrentTerm: typeof mockTerm = mockTerm

vi.mock('../hooks/useTerm', () => ({
  useTerm: () => ({
    data: mockCurrentTerm,
    isLoading: false,
    error: null,
  }),
  useTermExpanded: () => ({ data: undefined, isLoading: false, error: null }),
}))

vi.mock('../hooks/useClassTree', () => ({
  useClassTreeNodes: () => ({
    data: { terms: [{ iri: 'http://ex.org/A1', label: 'apoptosis' }] },
    isLoading: false,
  }),
}))

// Partial mock of the api client: keep every real export (profile/meta
// fetches TermPanel also makes, which just error out harmlessly against
// jsdom's fetch in this test environment, as in the pre-existing tests
// below) but override `ontologies.justification` and `reasoners.list` so
// each test controls what the reasoner "returns".
vi.mock('../lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../lib/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      ontologies: { ...actual.api.ontologies, justification: vi.fn() },
      reasoners: { list: vi.fn() },
    },
  }
})

import { api } from '../lib/api'
const mockJustification = api.ontologies.justification as ReturnType<typeof vi.fn>
const mockReasonersList = api.reasoners.list as ReturnType<typeof vi.fn>

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  mockCurrentTerm = mockTerm
  mockJustification.mockReset()
  mockReasonersList.mockReset()
  mockReasonersList.mockResolvedValue([])
})

test('shows term label and definition', () => {
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText('cell death')).toBeInTheDocument()
  expect(screen.getByText(/biological process/i)).toBeInTheDocument()
})

test('shows synonyms', () => {
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText(/cell killing/)).toBeInTheDocument()
})

test('shows superclasses', () => {
  // TermPanel renders Superclass section (no Subclasses section in the current
  // component). Assert the asserted superclass label is shown.
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)
  expect(screen.getByText('GO_0008150')).toBeInTheDocument()
})

describe('justification explain UI', () => {
  test('renders each justification as its list of Manchester axiom strings', async () => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
      { name: 'whelk', profile: 'EL', capabilities: ['classify', 'consistency', 'justify'], available: true },
    ])
    mockJustification.mockResolvedValue({
      justifications: [['A SubClassOf B', 'B SubClassOf C']],
      format: 'manchester',
      timed_out: false,
      reasoning_available: true,
    })

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" versionReasoner="whelk" />)

    const button = await screen.findByRole('button', { name: 'inference' })
    expect(button).not.toBeDisabled()
    fireEvent.click(button)

    // Lines are tokenised across spans now, so match on the line div's full text.
    const lineIs = (text: string) => (_: string, el: Element | null) =>
      el?.tagName === 'DIV' && el.textContent === text
    expect(await screen.findByText(lineIs('A SubClassOf B'))).toBeInTheDocument()
    expect(screen.getByText(lineIs('B SubClassOf C'))).toBeInTheDocument()
    // Keyword is highlighted as its own token (appears once per line).
    expect(screen.getAllByText('SubClassOf').length).toBe(2)
  })

  test('renders IRI tokens as clickable labelled links using the server labels map', async () => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
      { name: 'whelk', profile: 'EL', capabilities: ['classify', 'consistency', 'justify'], available: true },
    ])
    const A = 'http://purl.obolibrary.org/obo/GO_0000001'
    const B = 'http://purl.obolibrary.org/obo/GO_0000002'
    mockJustification.mockResolvedValue({
      justifications: [[`${A} SubClassOf ${B}`]],
      format: 'manchester',
      timed_out: false,
      reasoning_available: true,
      labels: { [A]: 'mitochondrion inheritance', [B]: 'reproduction' },
    })

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" versionReasoner="whelk" />)

    fireEvent.click(await screen.findByRole('button', { name: 'inference' }))

    // Full IRIs are shown as their real labels, linking to the term page.
    const link = await screen.findByRole('link', { name: 'mitochondrion inheritance' })
    expect(link).toHaveAttribute('href', `/ontologies/go/v1?term=${encodeURIComponent(A)}`)
    expect(link).toHaveAttribute('title', A)
    expect(screen.getByRole('link', { name: 'reproduction' })).toBeInTheDocument()
    // Raw IRIs no longer appear as visible text.
    expect(screen.queryByText(A)).not.toBeInTheDocument()
  })

  test('disables the inference button with a tooltip when the reasoner has no justify capability (konclude)', async () => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
      { name: 'konclude', profile: 'DL', capabilities: ['classify', 'consistency'], available: true },
    ])

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" versionReasoner="konclude" />)

    const button = await screen.findByRole('button', { name: 'inference' })
    await waitFor(() => expect(button).toBeDisabled())
    expect(button).toHaveAttribute('title', 'This reasoner does not produce explanations')
  })

  test.each(['whelk', 'rustdl'])('enables the inference button for %s (has justify)', async (reasonerName) => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
      { name: 'whelk', profile: 'EL', capabilities: ['classify', 'consistency', 'justify'], available: true },
      { name: 'rustdl', profile: 'DL', capabilities: ['classify', 'consistency', 'justify'], available: true },
      { name: 'konclude', profile: 'DL', capabilities: ['classify', 'consistency'], available: true },
    ])

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" versionReasoner={reasonerName} />)

    const button = await screen.findByRole('button', { name: 'inference' })
    await waitFor(() => expect(mockReasonersList).toHaveBeenCalled())
    await waitFor(() => expect(button).not.toBeDisabled())
    expect(button).toHaveAttribute('title', 'Show justification')
  })
})
