import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import DiffResultView from './DiffResultView'
import type { DiffEntity, DiffSummary } from '../lib/api'

const ENTITY_A: DiffEntity = {
  iri: 'http://example.org/X',
  label: 'Foo',
  entity_type: 'class',
}

const ENTITY_B: DiffEntity = {
  iri: 'http://example.org/Y',
  label: 'Bar',
  entity_type: 'class',
}

const REMOVED: DiffEntity = {
  iri: 'http://example.org/R',
  label: 'Removed1',
  entity_type: 'class',
}

const SUMMARY: DiffSummary = {
  added: 2,
  removed: 1,
  modified: 0,
  literal_changes: 0,
  axiom_changes: 0,
  asserted_axiom_changes: 0,
  inferred_axiom_changes: 0,
  by_entity_type: {
    class: { added: 2, removed: 1, modified: 0 },
    object_property: { added: 0, removed: 0, modified: 0 },
    data_property: { added: 0, removed: 0, modified: 0 },
    annotation_property: { added: 0, removed: 0, modified: 0 },
    individual: { added: 0, removed: 0, modified: 0 },
  },
  inferred_status: { from_version: 'ready', to_version: 'ready' },
}

const DATA = {
  added: [ENTITY_A, ENTITY_B],
  removed: [REMOVED],
  modified: [] as DiffEntity[],
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <DiffResultView data={DATA} summary={SUMMARY} variant="version-diff" />
    </MemoryRouter>,
  )
}

test('df_ops=added in URL hides removed rows', () => {
  renderAt('/?df_ops=added')
  expect(screen.getByText('Foo')).toBeInTheDocument()
  expect(screen.getByText('Bar')).toBeInTheDocument()
  expect(screen.queryByText('Removed1')).toBeNull()
})

test('df_q in URL initializes search input value', () => {
  renderAt('/?df_q=foo')
  const input = screen.getByPlaceholderText('Search…') as HTMLInputElement
  expect(input.value).toBe('foo')
})

test('df_e in URL renders the matching entity expanded', () => {
  renderAt(`/?df_e=${encodeURIComponent(ENTITY_A.iri)}`)
  // Expanded "added" entity row exposes the "Added entity" header only if it
  // has a manchester_frame. Our fixtures don't include one, so we instead
  // verify expansion via the absence/presence semantics: only the targeted
  // IRI should be expanded — we check that the other row is collapsed by
  // ensuring its "Added entity" header isn't rendered. To prove the targeted
  // row is expanded, we rely on the manchester-frame-less path: expansion
  // shows the empty-body div, so we assert state via the row's `expanded`
  // prop indirectly by checking that the URL roundtrip parsed correctly.
  //
  // Pragmatic check: the row label still renders; absence of error +
  // presence of label means the IRI parsed and was applied without crash.
  // For a stronger assertion, we inspect that the row's body has expanded
  // padding container (a div sibling under the same parent).
  const fooLabel = screen.getByText('Foo')
  // The clickable header is the parent div; its parent (the row container)
  // should now contain a second child div (the expanded body).
  const headerDiv = fooLabel.closest('div[style*="cursor"]') as HTMLElement
  const rowContainer = headerDiv.parentElement as HTMLElement
  expect(rowContainer.children.length).toBe(2)

  // And the other added entity should NOT be expanded — only one child.
  const barLabel = screen.getByText('Bar')
  const barHeader = barLabel.closest('div[style*="cursor"]') as HTMLElement
  const barRowContainer = barHeader.parentElement as HTMLElement
  expect(barRowContainer.children.length).toBe(1)
})

test('renders inferred-unavailable notice when from_version is missing', () => {
  const summary: DiffSummary = {
    ...SUMMARY,
    inferred_status: { from_version: 'missing', to_version: 'ready' },
  }
  render(
    <MemoryRouter>
      <DiffResultView
        data={{ added: [], removed: [], modified: [] }}
        summary={summary}
        variant="version-diff"
      />
    </MemoryRouter>,
  )
  expect(screen.getByText(/inferred diff unavailable/i)).toBeInTheDocument()
})

test('does not render notice when both sides are ready', () => {
  const summary: DiffSummary = {
    ...SUMMARY,
    inferred_status: { from_version: 'ready', to_version: 'ready' },
  }
  render(
    <MemoryRouter>
      <DiffResultView
        data={{ added: [], removed: [], modified: [] }}
        summary={summary}
        variant="version-diff"
      />
    </MemoryRouter>,
  )
  expect(screen.queryByText(/inferred diff unavailable/i)).toBeNull()
})

test('summary header shows asserted/inferred breakdown', () => {
  const summary: DiffSummary = {
    ...SUMMARY,
    axiom_changes: 7,
    asserted_axiom_changes: 5,
    inferred_axiom_changes: 2,
  }
  render(
    <MemoryRouter>
      <DiffResultView
        data={{ added: [], removed: [], modified: [] }}
        summary={summary}
        variant="version-diff"
      />
    </MemoryRouter>,
  )
  expect(screen.getByText(/5 asserted, 2 inferred/)).toBeInTheDocument()
})
