import { describe, it, expect, vi, beforeAll } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import OntologyPage from './OntologyPage'

const { mockOntology, mockVersion, mockRecordView } = vi.hoisted(() => ({
  mockRecordView: vi.fn().mockResolvedValue(undefined),
  mockOntology: {
    id: 'onto-1',
    iri: 'http://example.org/go',
    shortname: 'go',
    title: 'Gene Ontology',
    created_at: '2024-01-01T00:00:00Z',
    owner_display_name: 'Ada Lovelace',
    owner_orcid: '0000-0002-1825-0097',
  },
  mockVersion: {
    id: 'v1',
    ontology_id: 'onto-1',
    version_iri: 'http://example.org/go/v1',
    format: 'owl',
    status: 'ingested',
    sha256: 'abcdef1234567890',
    triple_count: 100,
    download_url: 'http://example.org/go/v1.owl',
    created_at: '2024-01-01T00:00:00Z',
    reasoner: 'rustdl',
  },
}))

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual('../lib/api')
  return {
    ...actual,
    api: {
      ...(actual as any).api,
      ontologies: {
        ...(actual as any).api.ontologies,
        list: vi.fn().mockResolvedValue({ ontologies: [mockOntology] }),
        recordView: mockRecordView,
        versions: vi.fn().mockResolvedValue({ versions: [mockVersion] }),
        stats: vi.fn().mockResolvedValue({
          triple_count: 100,
          class_count: 10,
          object_property_count: 2,
          datatype_property_count: 1,
          annotation_property_count: 1,
          individual_count: 0,
        }),
        ontologyMetadata: vi.fn().mockResolvedValue({
          predicates: {
            'http://purl.org/dc/terms/title': [{ value: 'GO', type: 'literal', language: null, datatype: null }],
            'http://www.w3.org/2000/01/rdf-schema#comment': [{ value: 'a comment', type: 'literal', language: null, datatype: null }],
          },
        }),
        languages: vi.fn().mockResolvedValue([]),
        // Meta profile maps dcterms:title (Title) but NOT rdfs:comment → comment
        // is unmapped and must be hidden from the Info metadata table.
        meta: {
          ...(actual as any).api.ontologies.meta,
          get: vi.fn().mockResolvedValue({
            version_id: 'v1', status: 'user_confirmed',
            title_props: ['http://purl.org/dc/terms/title'],
            description_props: [],
            resolved: {},
          }),
        },
      },
    },
  }
})

beforeAll(() => {
  // OntologyPage renders useIsMobile(), which needs window.matchMedia (jsdom lacks it).
  window.matchMedia = window.matchMedia || ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })) as unknown as typeof window.matchMedia
})

function wrap() {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/ontologies/go']}>
        <Routes>
          <Route path="/ontologies/:slug" element={<OntologyPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

describe('OntologyPage reasoner badge', () => {
  it('shows a Reasoner row with the value (and no duplicated label) for the active version', async () => {
    wrap()
    const label = await screen.findByText('Reasoner')
    const row = label.closest('tr')
    expect(row).not.toBeNull()
    expect(await screen.findByText('rustdl')).toBeInTheDocument()
    expect(row?.textContent).not.toMatch(/Reasoner:\s*rustdl/i)
  })
})

describe('OntologyPage view beacon', () => {
  it('POSTs a view beacon for the resolved ontology', async () => {
    wrap()
    await screen.findByText('Reasoner')  // wait until the page has resolved the ontology
    expect(mockRecordView).toHaveBeenCalledWith('onto-1')
  })
})

describe('OntologyPage document metadata honors the meta profile', () => {
  it('shows mapped predicates and hides unmapped ones', async () => {
    wrap()
    // dcterms:title is mapped (Title) → shown; rdfs:comment is unmapped → hidden.
    expect(await screen.findByText('Title')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByText('Comment')).not.toBeInTheDocument())
  })
})

describe('OntologyPage repository metadata', () => {
  it('shows an "Added by" row linking to the uploader\'s ORCID', async () => {
    wrap()
    const label = await screen.findByText('Added by')
    expect(label.closest('tr')).not.toBeNull()
    const link = await screen.findByRole('link', { name: /Ada Lovelace/ })
    expect(link).toHaveAttribute('href', 'https://orcid.org/0000-0002-1825-0097')
  })
})
