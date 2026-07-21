import { render, screen, fireEvent } from '@testing-library/react'
import SearchBar from './SearchBar'

// Controllable autocomplete mock — set `mockAc` per test.
let mockAc: { data: unknown } = { data: undefined }
vi.mock('../hooks/useSearch', () => ({
  useAutocomplete: () => mockAc,
  useGlobalAutocomplete: () => ({ data: undefined }),
}))

beforeEach(() => { mockAc = { data: undefined } })

const comp = (text: string) => ({ text, type: 'class', iri: text, short: null, insert: `${text} ` })
const withCompletions = (...texts: string[]) => ({
  data: { completions: texts.map(comp), replace_from: 0, replace_to: 1 },
})

test('renders with placeholder text', () => {
  render(<SearchBar ontologyId={null} versionId={null} onSearch={() => {}} />)
  expect(screen.getByPlaceholderText(/search terms/i)).toBeInTheDocument()
})

test('calls onSearch when Enter is pressed with no suggestion highlighted', () => {
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

test('arrow keys navigate and Tab accepts the highlighted suggestion', () => {
  mockAc = withCompletions('alpha', 'beta', 'gamma')
  const onSearch = vi.fn()
  render(<SearchBar ontologyId="o" versionId="v" onSearch={onSearch} />)
  const input = screen.getByPlaceholderText(/search terms/i) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'a' } })
  expect(screen.getByText('beta')).toBeInTheDocument()
  fireEvent.keyDown(input, { key: 'ArrowDown' })  // -> alpha (idx 0)
  fireEvent.keyDown(input, { key: 'ArrowDown' })  // -> beta  (idx 1)
  fireEvent.keyDown(input, { key: 'Tab' })
  expect(input.value).toBe('beta ')
  expect(onSearch).not.toHaveBeenCalled()
})

test('Enter accepts the highlighted suggestion instead of submitting', () => {
  mockAc = withCompletions('alpha', 'beta')
  const onSearch = vi.fn()
  render(<SearchBar ontologyId="o" versionId="v" onSearch={onSearch} />)
  const input = screen.getByPlaceholderText(/search terms/i) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'a' } })
  fireEvent.keyDown(input, { key: 'ArrowDown' })  // highlight alpha
  fireEvent.keyDown(input, { key: 'Enter' })
  expect(onSearch).not.toHaveBeenCalled()
  expect(input.value).toBe('alpha ')
})

test('Tab with nothing highlighted takes the top suggestion', () => {
  mockAc = withCompletions('alpha', 'beta')
  render(<SearchBar ontologyId="o" versionId="v" onSearch={() => {}} />)
  const input = screen.getByPlaceholderText(/search terms/i) as HTMLInputElement
  fireEvent.change(input, { target: { value: 'a' } })
  fireEvent.keyDown(input, { key: 'Tab' })
  expect(input.value).toBe('alpha ')
})
