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
  propertyTypes: {},
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
  propertyAxioms: [],
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

const { mockExpanded } = vi.hoisted(() => ({
  // Typed loosely on purpose: tests supply real expanded payloads, and
  // inferring the shape from the `data: undefined` default would forbid that.
  mockExpanded: vi.fn(
    (): { data: unknown; isLoading: boolean; error: unknown } =>
      ({ data: undefined, isLoading: false, error: null }),
  ),
}))

vi.mock('../hooks/useTerm', () => ({
  useTerm: () => ({
    data: mockCurrentTerm,
    isLoading: false,
    error: null,
  }),
  useTermExpanded: () => mockExpanded(),
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
      ontologies: { ...actual.api.ontologies, justification: vi.fn(), terms: vi.fn() },
      reasoners: { list: vi.fn() },
    },
  }
})

import { api } from '../lib/api'
const mockJustification = api.ontologies.justification as ReturnType<typeof vi.fn>
const mockReasonersList = api.reasoners.list as ReturnType<typeof vi.fn>
const mockTerms = api.ontologies.terms as ReturnType<typeof vi.fn>

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  mockExpanded.mockReturnValue({ data: undefined, isLoading: false, error: null })
  mockCurrentTerm = mockTerm
  mockJustification.mockReset()
  mockReasonersList.mockReset()
  mockReasonersList.mockResolvedValue([])
  // Default: classes have no instances (so the Instances section stays hidden
  // and unrelated class tests are unaffected). Specific tests override this.
  mockTerms.mockReset()
  mockTerms.mockResolvedValue({ terms: [], offset: 0, limit: 50, parent: null })
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

describe('individual object-property assertions', () => {
  const HAS_PARENT = 'http://example.org/family#hasParent'
  const BOB = 'http://example.org/family#bob'
  const CUSTOM_NOTE = 'http://example.org/family#note'

  const mockIndividual = {
    ...mockTerm,
    iri: 'http://example.org/family#alice',
    label: 'alice',
    definition: null,
    entityType: 'individual' as const,
    typeOf: [{ iri: 'http://example.org/family#Person', label: 'Person' }],
    rawProperties: {
      [HAS_PARENT]: [{ value: BOB, lang: null }],
      [CUSTOM_NOTE]: [{ value: 'a non-standard annotation', lang: null }],
    },
    propertyLabels: { [HAS_PARENT]: 'has parent' },
    // hasParent is a declared object property; note is an annotation property.
    propertyTypes: { [HAS_PARENT]: 'object_property', [CUSTOM_NOTE]: 'annotation_property' },
  }

  test('object-property assertions are shown by default, not hidden behind the annotations toggle', () => {
    // Cast: mockIndividual intentionally differs from the class-shaped mockTerm
    // (entityType, definition:null, typed typeOf) — only the runtime shape matters here.
    mockCurrentTerm = mockIndividual as unknown as typeof mockTerm
    wrap(<TermPanel ontologyId="family" versionId="v1" termIri="http://example.org/family#alice" slug="family" />)

    // Dedicated section header is present.
    expect(screen.getByText('Object property assertions')).toBeInTheDocument()
    // The target individual is a visible link WITHOUT clicking "View original annotations".
    const bob = screen.getByRole('link', { name: 'bob' })
    expect(bob).toHaveAttribute('href', `/ontologies/family/v1?term=${encodeURIComponent(BOB)}`)
    // The predicate label comes from propertyLabels.
    expect(screen.getByText('has parent')).toBeInTheDocument()

    // The genuine annotation stays gated: hidden until the toggle flips to original.
    expect(screen.queryByText('a non-standard annotation')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /View original annotations/ }))
    expect(screen.getByText('a non-standard annotation')).toBeInTheDocument()
    // The object-property value is not duplicated into the annotations table.
    expect(screen.getAllByRole('link', { name: 'bob' })).toHaveLength(1)
  })

  test('caps a high-fan-out assertion and reveals the rest via "show N more"', () => {
    const KNOWS = 'http://example.org/family#knows'
    const targets = Array.from({ length: 25 }, (_, i) => ({
      value: `http://example.org/family#p${i}`,
      lang: null,
    }))
    mockCurrentTerm = {
      ...mockTerm,
      iri: 'http://example.org/family#hub',
      entityType: 'individual' as const,
      definition: null,
      rawProperties: { [KNOWS]: targets },
      propertyLabels: { [KNOWS]: 'knows' },
      propertyTypes: { [KNOWS]: 'object_property' },
    } as unknown as typeof mockTerm

    wrap(<TermPanel ontologyId="family" versionId="v1" termIri="http://example.org/family#hub" slug="family" />)

    // Only the first 20 of 25 values render initially.
    expect(screen.getByRole('link', { name: 'p0' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'p19' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'p20' })).not.toBeInTheDocument()

    // Expander reveals the remaining 5.
    fireEvent.click(screen.getByRole('button', { name: 'show 5 more' }))
    expect(screen.getByRole('link', { name: 'p24' })).toBeInTheDocument()
  })
})

describe('used-in-axioms Manchester rendering', () => {
  test('renders property usage as a Manchester axiom line with clickable IRIs', () => {
    mockCurrentTerm = {
      ...mockTerm,
      iri: 'http://ex.org/hasFather',
      entityType: 'object_property' as const,
      usage: [{
        class_iri: 'http://ex.org/Man', class_label: 'Man',
        relation: 'subClassOf', restriction: 'some',
        filler_iri: 'http://ex.org/Man', filler_label: 'Man', filler_expr: null,
        manchester: [
          { t: 'iri', label: 'Man', iri: 'http://ex.org/Man', in_ontology: true },
          { t: 'text', v: ' SubClassOf ' },
          { t: 'iri', label: 'hasFather', iri: 'http://ex.org/hasFather', in_ontology: true },
          { t: 'text', v: ' some ' },
          { t: 'iri', label: 'Man', iri: 'http://ex.org/Man', in_ontology: true },
        ],
      }],
      usageHasMore: false,
    } as unknown as typeof mockTerm

    wrap(<TermPanel ontologyId="fam" versionId="v1" termIri="http://ex.org/hasFather" slug="fam" />)

    // The full axiom renders as one line.
    const line = screen.getByText(
      (_t, el) => el?.tagName === 'DIV' && el.textContent === 'Man SubClassOf hasFather some Man',
    )
    expect(line).toBeInTheDocument()
    // IRIs are clickable, version-pinned links.
    const manLink = screen.getAllByRole('link', { name: 'Man' })[0]
    expect(manLink).toHaveAttribute(
      'href', `/ontologies/fam/v1?term=${encodeURIComponent('http://ex.org/Man')}`)
    expect(screen.getAllByRole('link', { name: 'hasFather' }).length).toBeGreaterThanOrEqual(1)
  })
})

describe('property axioms in Manchester (subPropertyOf / chain)', () => {
  test('renders a "Property axioms" section incl. a property chain, clickable', () => {
    mockCurrentTerm = {
      ...mockTerm,
      iri: 'http://ex.org/hasGrandparent',
      entityType: 'object_property' as const,
      propertyAxioms: [
        [
          { t: 'iri', label: 'hasGrandparent', iri: 'http://ex.org/hasGrandparent', in_ontology: true },
          { t: 'text', v: ' SubPropertyChain ' },
          { t: 'iri', label: 'hasParent', iri: 'http://ex.org/hasParent', in_ontology: true },
          { t: 'text', v: ' o ' },
          { t: 'iri', label: 'hasParent', iri: 'http://ex.org/hasParent', in_ontology: true },
        ],
      ],
    } as unknown as typeof mockTerm

    wrap(<TermPanel ontologyId="fam" versionId="v1" termIri="http://ex.org/hasGrandparent" slug="fam" />)

    expect(screen.getByText('Property axioms')).toBeInTheDocument()
    const line = screen.getByText(
      (_t, el) => el?.tagName === 'DIV'
        && el.textContent === 'hasGrandparent SubPropertyChain hasParent o hasParent',
    )
    expect(line).toBeInTheDocument()
    const link = screen.getAllByRole('link', { name: 'hasParent' })[0]
    expect(link).toHaveAttribute(
      'href', `/ontologies/fam/v1?term=${encodeURIComponent('http://ex.org/hasParent')}`)
  })
})

describe('property super-properties list', () => {
  test('renders a "Super-properties" section from subPropertyOf, clickable', () => {
    mockCurrentTerm = {
      ...mockTerm,
      iri: 'http://ex.org/hasFather',
      entityType: 'object_property' as const,
      rawProperties: {
        'http://www.w3.org/2000/01/rdf-schema#subPropertyOf': [
          { value: 'http://ex.org/hasParent', lang: null },
        ],
      },
    } as unknown as typeof mockTerm

    wrap(<TermPanel ontologyId="fam" versionId="v1" termIri="http://ex.org/hasFather" slug="fam" />)

    expect(screen.getByText('Super-properties (1)')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'hasParent' })
    expect(link).toHaveAttribute(
      'href', `/ontologies/fam/v1?term=${encodeURIComponent('http://ex.org/hasParent')}`)
  })
})

describe('property sub-properties list', () => {
  test('lists direct sub-properties as clickable links', async () => {
    mockCurrentTerm = {
      ...mockTerm,
      iri: 'http://ex.org/contains',
      entityType: 'object_property' as const,
    } as unknown as typeof mockTerm
    mockTerms.mockResolvedValue({
      terms: [{ iri: 'http://ex.org/hasPart', label: 'has part', lang: null, has_children: false, source: '' }],
      offset: 0, limit: 50, parent: 'http://ex.org/contains',
    })

    wrap(<TermPanel ontologyId="pizza" versionId="v1" termIri="http://ex.org/contains" slug="pizza" />)

    expect(await screen.findByText('Sub-properties (1)')).toBeInTheDocument()
    const link = screen.getByRole('link', { name: 'has part' })
    expect(link).toHaveAttribute(
      'href', `/ontologies/pizza/v1?term=${encodeURIComponent('http://ex.org/hasPart')}`)
    // Queried children of this property, scoped to its own entity type.
    expect(mockTerms).toHaveBeenCalledWith(
      'pizza', 'v1', 'http://ex.org/contains', 'object_property', false, true, 50, 0, undefined)
  })
})

describe('class instances section', () => {
  test('lists a class\'s individuals, paged, and hidden when there are none', async () => {
    // mockTerm is a class; return two instances for it.
    mockTerms.mockResolvedValue({
      terms: [
        { iri: 'http://ex.org/i/alice', label: 'Alice', lang: null, has_children: false, source: '' },
        { iri: 'http://ex.org/i/bob', label: 'Bob', lang: null, has_children: false, source: '' },
      ],
      offset: 0, limit: 50, parent: 'http://purl.obolibrary.org/obo/GO_0008219',
    })

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)

    expect(await screen.findByText('Instances (2)')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Alice' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Bob' })).toBeInTheDocument()
    // Requested individuals for this class IRI, not classes.
    expect(mockTerms).toHaveBeenCalledWith(
      'go', 'v1', 'http://purl.obolibrary.org/obo/GO_0008219', 'individual',
      false, true, 50, 0, undefined,
    )
  })
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
    // Multi-word labels are single-quoted, matching the axioms description.
    const link = await screen.findByRole('link', { name: "'mitochondrion inheritance'" })
    expect(link).toHaveAttribute('href', `/ontologies/go/v1?term=${encodeURIComponent(A)}`)
    expect(link).toHaveAttribute('title', A)
    expect(screen.getByRole('link', { name: 'reproduction' })).toBeInTheDocument()
    // Raw IRIs no longer appear as visible text.
    expect(screen.queryByText(A)).not.toBeInTheDocument()
  })

  test('renders angle-bracketed IRIs (the reasoner render format) as clickable labelled links', async () => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
      { name: 'rustdl', profile: 'DL', capabilities: ['classify', 'consistency', 'justify'], available: true },
    ])
    const A = 'http://ex.org/Puppy'
    const B = 'http://ex.org/Dog'
    mockJustification.mockResolvedValue({
      // rustdl.render_manchester emits IRIs wrapped in angle brackets.
      justifications: [[`<${A}> SubClassOf <${B}>`]],
      format: 'manchester',
      timed_out: false,
      reasoning_available: true,
      labels: { [A]: 'Puppy', [B]: 'Dog' },
    })

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" versionReasoner="rustdl" />)

    fireEvent.click(await screen.findByRole('button', { name: 'inference' }))

    const puppy = await screen.findByRole('link', { name: 'Puppy' })
    expect(puppy).toHaveAttribute('href', `/ontologies/go/v1?term=${encodeURIComponent(A)}`)
    expect(puppy).toHaveAttribute('title', A)
    expect(screen.getByRole('link', { name: 'Dog' })).toBeInTheDocument()
    // The raw <...> IRI text must not survive as plain text.
    expect(screen.queryByText(`<${A}>`)).not.toBeInTheDocument()
  })

  test('disables the inference button with a tooltip when NO justify-capable reasoner is up', async () => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
      { name: 'konclude', profile: 'DL', capabilities: ['classify', 'consistency'], available: true },
    ])

    wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" versionReasoner="konclude" />)

    const button = await screen.findByRole('button', { name: 'inference' })
    await waitFor(() => expect(button).toBeDisabled())
    expect(button).toHaveAttribute('title', 'Justification unavailable — no justify-capable reasoner is up')
  })

  // Justification is reasoner-agnostic: even a konclude-classified version can be
  // explained as long as a justify-capable reasoner (rustdl) is in the catalog.
  test.each(['whelk', 'rustdl', 'konclude'])('enables the inference button for a %s version when a justifier is up', async (reasonerName) => {
    mockCurrentTerm = mockTermWithInferredSuper
    mockReasonersList.mockResolvedValue([
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


// ── deferred-section loading ──────────────────────────────────────────────────
// The sections that come from /term-expanded render nothing until it resolves,
// so "no usages" and "usages still loading" looked identical — a ~4 s window on
// a large ontology in which the panel appears complete and is not.

test('shows a Loading… placeholder for deferred sections while they load', async () => {
  mockExpanded.mockReturnValue({ data: undefined, isLoading: true, error: null })
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)

  expect(await screen.findByText('Used in axioms')).toBeInTheDocument()
  expect(screen.getByText('Inherited domain of')).toBeInTheDocument()
  expect(screen.getAllByText('Loading…').length).toBeGreaterThanOrEqual(2)
})

test('replaces the placeholder with content once the deferred fetch resolves', async () => {
  mockExpanded.mockReturnValue({
    isLoading: false, error: null,
    data: {
      inferredSuperclassExpressions: [], inferredDisjointWith: [],
      inheritedSchemaProperties: [],
      classUsage: [{ iri: 'http://ex.org/C1', label: 'uses it', manchester: null }],
      classUsageHasMore: false,
    },
  })
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)

  expect(await screen.findByText(/Used in axioms \(1\)/)).toBeInTheDocument()
  expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
})

test('drops an empty deferred section rather than leaving a placeholder', async () => {
  mockExpanded.mockReturnValue({
    isLoading: false, error: null,
    data: {
      inferredSuperclassExpressions: [], inferredDisjointWith: [],
      inheritedSchemaProperties: [], classUsage: [], classUsageHasMore: false,
    },
  })
  wrap(<TermPanel ontologyId="go" versionId="v1" termIri="http://purl.obolibrary.org/obo/GO_0008219" slug="go" />)

  await waitFor(() => expect(screen.queryByText('Loading…')).not.toBeInTheDocument())
  expect(screen.queryByText('Used in axioms')).not.toBeInTheDocument()
  expect(screen.queryByText('Inherited domain of')).not.toBeInTheDocument()
})
