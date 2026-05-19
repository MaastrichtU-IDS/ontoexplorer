import { render, screen, fireEvent } from '@testing-library/react'
import SearchBar from './SearchBar'

vi.mock('../hooks/useSearch', () => ({
  useAutocomplete: () => ({ data: undefined }),
  useGlobalAutocomplete: () => ({ data: undefined }),
}))

test('renders with placeholder text', () => {
  render(<SearchBar ontologyId={null} versionId={null} onSearch={() => {}} />)
  expect(screen.getByPlaceholderText(/search terms/i)).toBeInTheDocument()
})

test('calls onSearch when Enter is pressed', () => {
  const onSearch = vi.fn()
  render(<SearchBar ontologyId={null} versionId={null} onSearch={onSearch} />)
  const input = screen.getByPlaceholderText(/search terms/i)
  fireEvent.change(input, { target: { value: 'cell death' } })
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(onSearch).toHaveBeenCalledWith('cell death')
})

test('accepts custom placeholder', () => {
  render(<SearchBar ontologyId={null} versionId={null} onSearch={() => {}} placeholder="Find stuff…" />)
  expect(screen.getByPlaceholderText('Find stuff…')).toBeInTheDocument()
})
