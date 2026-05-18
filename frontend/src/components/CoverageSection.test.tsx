import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CoverageSection from './CoverageSection'

const RECORD = {
  version_id: 'v1',
  indexed_at: '2026-05-18T12:00:00Z',
  by_type: {
    class: {
      total: 1000, with_label: 950, with_definition: 500, multilingual: 100,
      by_lang: { en: 950, de: 80, fr: 20, '': 5 },
    },
    object_property:     { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
    data_property:       { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
    annotation_property: { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
    individual:          { total: 0, with_label: 0, with_definition: 0, multilingual: 0, by_lang: {} },
  },
}

vi.mock('../lib/api', () => ({
  api: { coverage: { version: () => Promise.resolve(RECORD) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

test('renders cards for each entity type with em-dash on zero totals', async () => {
  wrap(<CoverageSection ontologyId="o1" versionId="v1" />)
  expect(await screen.findByTestId('coverage-card-class')).toBeInTheDocument()
  expect(screen.getByTestId('coverage-card-class').textContent).toMatch(/95%/)
  expect(screen.getByTestId('coverage-card-object_property').textContent).toMatch(/—/)
})

test('renders language bar segments sorted by count desc, with (no lang) for empty tag', async () => {
  wrap(<CoverageSection ontologyId="o1" versionId="v1" />)
  const bar = await screen.findByTestId('lang-bar')
  const text = bar.textContent || ''
  const enIdx = text.indexOf('en:')
  const deIdx = text.indexOf('de:')
  const noIdx = text.indexOf('(no lang)')
  expect(enIdx).toBeGreaterThan(-1)
  expect(deIdx).toBeGreaterThan(enIdx)
  expect(noIdx).toBeGreaterThan(deIdx)
})
