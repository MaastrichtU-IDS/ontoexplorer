import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ScopeToolbar } from './ScopeToolbar'

vi.mock('../../hooks/useOntologies', () => ({
  useOntologies: () => ({
    ontologies: [],
    isLoading: false,
  }),
}))

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>
}

const SAMPLE_ONTS = [
  {
    id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
    created_at: '2024-01-01',
    latest_version: { id: 'V1', ontology_id: 'O1', status: 'ready' } as any,
  } as any,
  {
    id: 'O2', iri: 'http://x/o2', shortname: 'chebi', title: 'ChEBI',
    created_at: '2024-01-01',
    latest_version: { id: 'V2', ontology_id: 'O2', status: 'ready' } as any,
  } as any,
]

vi.doMock('../../hooks/useOntologies', () => ({
  useOntologies: () => ({ ontologies: SAMPLE_ONTS, isLoading: false }),
}))

describe('ScopeToolbar — selecting ontologies', () => {
  it('lists ontologies in the popover when opened', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    expect(screen.getByText('envo')).toBeInTheDocument()
    expect(screen.getByText('chebi')).toBeInTheDocument()
  })

  it('adds a chip on click and calls onScopeChange with the scoped URL', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(onScope).toHaveBeenLastCalledWith(
      '/api/v1/sparql/content?default-graph-uri=urn%3Aontology%3AO1%3AV1&named-graph-uri=urn%3Aontology%3AO1%3AV1'
    )
    expect(screen.getByRole('button', { name: /envo ✕/i })).toBeInTheDocument()
  })

  it('removes a chip and calls onScopeChange with the base URL', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /envo ✕/i }))
    expect(onScope).toHaveBeenLastCalledWith('/api/v1/sparql/content')
  })

  it('filters the popover list', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    const input = screen.getByPlaceholderText(/filter/i)
    fireEvent.change(input, { target: { value: 'che' } })
    expect(screen.queryByText('envo')).not.toBeInTheDocument()
    expect(screen.getByText('chebi')).toBeInTheDocument()
  })
})

describe('ScopeToolbar — reasoning mode', () => {
  it('reasoning controls become enabled after first selection', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(screen.getByRole('button', { name: /asserted/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /inferred/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /both/i })).not.toBeDisabled()
  })

  it('switching to Inferred re-emits the endpoint with the inferred URI', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /inferred/i }))
    expect(onScope).toHaveBeenLastCalledWith(
      '/api/v1/sparql/content?default-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred&named-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred'
    )
  })

  it('switching to Both emits four URL params per ontology', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /both/i }))
    const url = onScope.mock.calls[onScope.mock.calls.length - 1]?.[0] as string
    expect(url).toContain('default-graph-uri=urn%3Aontology%3AO1%3AV1&')
    expect(url).toContain('named-graph-uri=urn%3Aontology%3AO1%3AV1&')
    expect(url).toContain('default-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred')
    expect(url).toContain('named-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred')
  })
})

describe('ScopeToolbar — empty state', () => {
  it('shows the "No scope" summary when nothing is selected', () => {
    render(wrap(
      <ScopeToolbar
        onScopeChange={vi.fn()}
        onCopy={vi.fn()}
      />
    ))
    expect(screen.getByText(/No scope selected/i)).toBeInTheDocument()
  })

  it('renders three reasoning options, all disabled', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    const asserted = screen.getByRole('button', { name: /asserted/i })
    const inferred = screen.getByRole('button', { name: /inferred/i })
    const both = screen.getByRole('button', { name: /both/i })
    expect(asserted).toBeDisabled()
    expect(inferred).toBeDisabled()
    expect(both).toBeDisabled()
  })

  it('renders an "add ontology" button', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    expect(screen.getByRole('button', { name: /add ontology/i })).toBeInTheDocument()
  })

  it('renders a copy button', () => {
    render(wrap(
      <ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />
    ))
    expect(screen.getByRole('button', { name: /copy query with scope/i })).toBeInTheDocument()
  })
})

describe('ScopeToolbar — copy icon', () => {
  it('emits empty string when no ontologies selected', () => {
    const onCopy = vi.fn()
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={onCopy} />))
    fireEvent.click(screen.getByRole('button', { name: /copy query with scope/i }))
    expect(onCopy).toHaveBeenCalledWith('')
  })

  it('emits FROM + FROM NAMED lines for a selected ontology in Both mode', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onCopy = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={onCopy} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    fireEvent.click(screen.getByRole('button', { name: /both/i }))
    fireEvent.click(screen.getByRole('button', { name: /copy query with scope/i }))
    expect(onCopy).toHaveBeenLastCalledWith(
      'FROM <urn:ontology:O1:V1>\nFROM NAMED <urn:ontology:O1:V1>\n' +
      'FROM <urn:ontology:O1:V1:inferred>\nFROM NAMED <urn:ontology:O1:V1:inferred>\n'
    )
  })
})
