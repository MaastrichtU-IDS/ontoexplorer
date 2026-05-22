import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
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
    expect(screen.getByRole('button', { name: /remove envo/i })).toBeInTheDocument()
  })

  it('removes a chip and calls onScopeChange with the base URL', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onScope = vi.fn()
    render(wrap(<Fresh onScopeChange={onScope} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onScope.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /remove envo/i }))
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
      '/api/v1/sparql/content' +
      '?default-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred' +
      '&named-graph-uri=urn%3Aontology%3AO1%3AV1%3Ainferred'
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

describe('ScopeToolbar — onOntologyAdded callback', () => {
  it('fires with the ontology id on chip add', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onAdded = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onOntologyAdded={onAdded} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(onAdded).toHaveBeenCalledWith('O1')
  })

  it('does not fire on chip remove', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onAdded = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onOntologyAdded={onAdded} />))
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    onAdded.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /remove envo/i }))
    expect(onAdded).not.toHaveBeenCalled()
  })

  it('does not fire on initial render with empty selection', () => {
    const onAdded = vi.fn()
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} onOntologyAdded={onAdded} />))
    expect(onAdded).not.toHaveBeenCalled()
  })
})

describe('ScopeToolbar — onSelectionChange callback', () => {
  it('fires with the current ids whenever selection changes', async () => {
    vi.resetModules()
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onSel = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onSelectionChange={onSel} />))
    // Initial render fires with []
    expect(onSel).toHaveBeenCalledWith([])
    onSel.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /add ontology/i }))
    fireEvent.click(screen.getByText('envo'))
    expect(onSel).toHaveBeenLastCalledWith(['O1'])
  })
})

describe('ScopeToolbar — labels toggle', () => {
  it('renders a labels toggle button', () => {
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    expect(screen.getByRole('button', { name: /toggle result labels/i })).toBeInTheDocument()
  })

  it('fires onLabelsToggle(true) on first click and (false) on second click', () => {
    const onToggle = vi.fn()
    render(wrap(<ScopeToolbar onScopeChange={vi.fn()} onCopy={vi.fn()} onLabelsToggle={onToggle} />))
    const btn = screen.getByRole('button', { name: /toggle result labels/i })
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenLastCalledWith(true)
    fireEvent.click(btn)
    expect(onToggle).toHaveBeenLastCalledWith(false)
  })
})

describe('ScopeToolbar — Diff mode', () => {
  beforeEach(() => {
    vi.resetModules()
  })

  it('renders the Single ↔ Diff mode toggle', async () => {
    vi.doMock('../../hooks/useOntologies', () => ({
      useOntologies: () => ({
        ontologies: [
          { id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
            created_at: '2024-01-01',
            latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } as any,
          } as any,
        ],
        isLoading: false,
      }),
    }))
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    expect(screen.getByRole('button', { name: /^single$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^diff$/i })).toBeInTheDocument()
  })

  it('clicking Diff reveals From and To picker rows', async () => {
    vi.doMock('../../hooks/useOntologies', () => ({
      useOntologies: () => ({
        ontologies: [
          { id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
            created_at: '2024-01-01',
            latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } as any,
          } as any,
        ],
        isLoading: false,
      }),
    }))
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} />))
    fireEvent.click(screen.getByRole('button', { name: /^diff$/i }))
    expect(await screen.findByText(/from:/i)).toBeInTheDocument()
    expect(screen.getByText(/to:/i)).toBeInTheDocument()
  })

  it('selecting both sides fires onDiffScopeChange with the full version objects', async () => {
    const SAMPLE_VERSIONS = [
      { id: 'V2', ontology_id: 'O1', status: 'ready', format: 'owl',
        version_iri: 'env-2.0', sha256: '', triple_count: 0, download_url: '', created_at: '2026-05-20' },
      { id: 'V1', ontology_id: 'O1', status: 'ready', format: 'owl',
        version_iri: 'env-1.0', sha256: '', triple_count: 0, download_url: '', created_at: '2024-01-01' },
    ]
    vi.doMock('../../hooks/useOntologies', () => ({
      useOntologies: () => ({
        ontologies: [
          { id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
            created_at: '2024-01-01',
            latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } as any,
          } as any,
        ],
        isLoading: false,
      }),
    }))
    vi.doMock('../../lib/api', async () => {
      const actual = await vi.importActual<any>('../../lib/api')
      return {
        ...actual,
        api: {
          ...actual.api,
          ontologies: {
            ...actual.api.ontologies,
            versions: vi.fn().mockResolvedValue({ versions: SAMPLE_VERSIONS }),
          },
        },
      }
    })
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onDiff = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onDiffScopeChange={onDiff} />))
    fireEvent.click(screen.getByRole('button', { name: /^diff$/i }))
    // Wait for the diff scope to settle; both sides default to envo's latest two versions
    await waitFor(() => {
      expect(onDiff).toHaveBeenCalled()
      const last = onDiff.mock.calls[onDiff.mock.calls.length - 1]?.[0]
      expect(last).not.toBeNull()
      expect(last.from.version.id).toBe('V1')
      expect(last.from.version.ontology_id).toBe('O1')
      expect(last.to.version.id).toBe('V2')
      expect(last.to.version.ontology_id).toBe('O1')
      expect(last.from.mode).toBe('asserted')
      expect(last.to.mode).toBe('asserted')
    })
  })

  it('toggling back to Single fires onDiffScopeChange(null)', async () => {
    vi.doMock('../../hooks/useOntologies', () => ({
      useOntologies: () => ({
        ontologies: [
          { id: 'O1', iri: 'http://x/o1', shortname: 'envo', title: 'ENVO',
            created_at: '2024-01-01',
            latest_version: { id: 'V2', ontology_id: 'O1', status: 'ready' } as any,
          } as any,
        ],
        isLoading: false,
      }),
    }))
    const { ScopeToolbar: Fresh } = await import('./ScopeToolbar')
    const onDiff = vi.fn()
    render(wrap(<Fresh onScopeChange={vi.fn()} onCopy={vi.fn()} onDiffScopeChange={onDiff} />))
    fireEvent.click(screen.getByRole('button', { name: /^diff$/i }))
    onDiff.mockClear()
    fireEvent.click(screen.getByRole('button', { name: /^single$/i }))
    expect(onDiff).toHaveBeenCalledWith(null)
  })
})
