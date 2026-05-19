import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ClassTree from './ClassTree'

const rootTerms = [
  { iri: 'http://ex.org/A', label: 'Term A' },
  { iri: 'http://ex.org/B', label: 'Term B' },
]
const childTerms = [{ iri: 'http://ex.org/A1', label: 'Term A1' }]

vi.mock('../hooks/useClassTree', () => ({
  useClassTreeNodes: (_oid: string | null, _vid: string | null, parent: string | null) => ({
    data: { terms: parent && parent !== 'root' ? childTerms : rootTerms },
    isLoading: false,
  }),
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

test('selected node has accent color', () => {
  wrap(<ClassTree ontologyId="go" versionId="v1" selectedIri="http://ex.org/A" onSelect={() => {}} />)
  const node = screen.getByText('Term A').closest('div')!
  // The clickable row uses style.color; selected -> var(--accent)
  // closest('div') gives the inner span wrapper, so walk to find the row.
  // The row is the parent div with the data-iri attribute.
  const row = (node.closest('[data-iri]') as HTMLElement) ?? node
  expect(row.style.color).toBe('var(--accent)')
})
