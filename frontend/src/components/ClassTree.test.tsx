import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ClassTree from './ClassTree'

// A, B expandable; C a leaf root. A and B share the SAME child D — so D appears
// on two rows (a DAG, as in the inferred tree). This is what broke IRI-indexed
// keyboard nav.
const rootTerms = [
  { iri: 'http://ex.org/A', label: 'Term A' },
  { iri: 'http://ex.org/B', label: 'Term B' },
  { iri: 'http://ex.org/C', label: 'Term C', has_children: false },
]
const childTerms = [{ iri: 'http://ex.org/A1', label: 'Term A1' }]
const childrenOf: Record<string, { iri: string; label: string; has_children: boolean }[]> = {
  'http://ex.org/A': [{ iri: 'http://ex.org/D', label: 'Term D', has_children: false }],
  'http://ex.org/B': [{ iri: 'http://ex.org/D', label: 'Term D', has_children: false }],
}

vi.mock('../hooks/useClassTree', () => ({
  useClassTreeNodes: (_oid: string | null, _vid: string | null, parent: string | null) => {
    if (!parent || parent === 'root') return { data: { terms: rootTerms }, isLoading: false }
    return { data: { terms: childrenOf[parent] ?? childTerms }, isLoading: false }
  },
}))

vi.mock('../hooks/useInferredTree', () => ({
  useInferredTreeNodes: () => ({
    data: { terms: [], reasoning_available: true },
    isLoading: false,
  }),
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

test('renders root terms', () => {
  wrap(<ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={() => {}} />)
  expect(screen.getByText('Term A')).toBeInTheDocument()
  expect(screen.getByText('Term B')).toBeInTheDocument()
})

test('clicking a node calls onSelect with its IRI', () => {
  const onSelect = vi.fn()
  wrap(<ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={onSelect} />)
  fireEvent.click(screen.getByText('Term A'))
  expect(onSelect).toHaveBeenCalledWith('http://ex.org/A')
})

test('ArrowDown traverses every unique row in a DAG instead of looping', () => {
  const { container } = wrap(
    <ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={() => {}} />,
  )
  const toggle = (iri: string) =>
    container.querySelector(`[data-iri="${iri}"] [data-toggle]`) as HTMLElement
  // Expand A and B → their shared child D renders on two rows.
  fireEvent.click(toggle('http://ex.org/A'))
  fireEvent.click(toggle('http://ex.org/B'))

  // DOM order: A, D(@A), B, D(@B), C. Five ArrowDowns from the top must reach
  // the LAST row (C). The old IRI-indexed nav looped between B and the first D
  // (mirroring the Father/Parent loop) and never got past it.
  const tree = container.querySelector('div[tabindex="0"]') as HTMLElement
  for (let i = 0; i < 5; i++) fireEvent.keyDown(tree, { key: 'ArrowDown' })

  const cRow = container.querySelector('[data-iri="http://ex.org/C"]') as HTMLElement
  expect(cRow.style.outline).toContain('var(--accent)')
})

test('selected node has accent color', () => {
  wrap(<ClassTree ontologyId="go" versionId="v1" selectedIri="http://ex.org/A" onSelect={() => {}} />)
  const node = screen.getByText('Term A').closest('div')!
  // The clickable row uses style.color; selected -> var(--accent)
  // closest('div') gives the inner span wrapper, so walk to find the row.
  // The row is the parent div with the data-iri attribute.
  const row = (node.closest('[data-iri]') as HTMLElement) ?? node
  expect(row.style.color).toBe('var(--accent)')
})
