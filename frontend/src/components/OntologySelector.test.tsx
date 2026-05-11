import { render, screen, fireEvent } from '@testing-library/react'
import OntologySelector from './OntologySelector'

vi.mock('../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [
      { id: 'go', iri: 'http://go', created_at: '2024-01-01' },
      { id: 'mondo', iri: 'http://mondo', created_at: '2024-01-01' },
    ],
    isLoading: false,
  }),
}))

test('renders All option by default', () => {
  render(<OntologySelector value={null} onChange={() => {}} />)
  expect(screen.getByText('All')).toBeInTheDocument()
  expect(screen.getByText('go')).toBeInTheDocument()
})

test('calls onChange when option selected', () => {
  const onChange = vi.fn()
  render(<OntologySelector value={null} onChange={onChange} />)
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'go' } })
  expect(onChange).toHaveBeenCalledWith('go')
})

test('renders required mode with no All option', () => {
  render(<OntologySelector value={null} onChange={() => {}} required placeholder="Pick one…" />)
  expect(screen.queryByText('All')).not.toBeInTheDocument()
  expect(screen.getByText('Pick one…')).toBeInTheDocument()
})
