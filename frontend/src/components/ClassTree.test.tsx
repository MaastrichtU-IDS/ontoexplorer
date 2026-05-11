import { render, screen, fireEvent } from '@testing-library/react'
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

test('renders root terms', () => {
  render(<ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={() => {}} />)
  expect(screen.getByText('Term A')).toBeInTheDocument()
  expect(screen.getByText('Term B')).toBeInTheDocument()
})

test('clicking a node calls onSelect with its IRI', () => {
  const onSelect = vi.fn()
  render(<ClassTree ontologyId="go" versionId="v1" selectedIri={null} onSelect={onSelect} />)
  fireEvent.click(screen.getByText('Term A'))
  expect(onSelect).toHaveBeenCalledWith('http://ex.org/A')
})

test('selected node has accent color', () => {
  render(<ClassTree ontologyId="go" versionId="v1" selectedIri="http://ex.org/A" onSelect={() => {}} />)
  const node = screen.getByText('Term A').closest('div')!
  expect(node.style.color).toBe('var(--accent)')
})
