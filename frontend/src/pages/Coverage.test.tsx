import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import Coverage from './Coverage'

const FLEET = {
  totals: {
    class:               { total: 1000, with_label: 950, with_definition: 500, multilingual: 100 },
    object_property:     { total:   50, with_label:  48, with_definition:  10, multilingual:   0 },
    data_property:       { total:   10, with_label:  10, with_definition:   0, multilingual:   0 },
    annotation_property: { total:    5, with_label:   5, with_definition:   0, multilingual:   0 },
    individual:          { total:    0, with_label:   0, with_definition:   0, multilingual:   0 },
  },
  by_ontology: [
    { ontology_id: 'o1', version_id: 'v1', shortname: 'go',  title: 'Gene Ontology', indexed_at: '2026-05-18T00:00:00Z',
      by_type: {
        class:               { total: 800, with_label: 800, with_definition: 400, multilingual: 80 },
        object_property:     { total:  40, with_label:  40, with_definition:  10, multilingual:  0 },
        data_property:       { total:   5, with_label:   5, with_definition:   0, multilingual:  0 },
        annotation_property: { total:   3, with_label:   3, with_definition:   0, multilingual:  0 },
        individual:          { total:   0, with_label:   0, with_definition:   0, multilingual:  0 },
      } },
    { ontology_id: 'o2', version_id: 'v2', shortname: 'sulo', title: 'SULO', indexed_at: '2026-05-18T00:00:00Z',
      by_type: {
        class:               { total: 200, with_label: 150, with_definition: 100, multilingual: 20 },
        object_property:     { total:  10, with_label:   8, with_definition:   0, multilingual:  0 },
        data_property:       { total:   5, with_label:   5, with_definition:   0, multilingual:  0 },
        annotation_property: { total:   2, with_label:   2, with_definition:   0, multilingual:  0 },
        individual:          { total:   0, with_label:   0, with_definition:   0, multilingual:  0 },
      } },
  ],
}

vi.mock('../lib/api', () => ({
  api: { coverage: { fleet: () => Promise.resolve(FLEET) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders fleet summary cards and per-ontology rows', async () => {
  wrap(<Coverage />)
  expect(await screen.findByText('Gene Ontology')).toBeInTheDocument()
  expect(screen.getByText('SULO')).toBeInTheDocument()
  // 950 / 1000 class labels = 95%
  expect(screen.getByText('95%')).toBeInTheDocument()
})

test('sort by class label % toggles ascending and descending', async () => {
  const user = userEvent.setup()
  wrap(<Coverage />)
  await screen.findByText('Gene Ontology')

  const labelHeader = screen.getByRole('button', { name: /class label %/i })
  await user.click(labelHeader) // ascending
  let rows = screen.getAllByTestId('coverage-row').map(r => within(r).getByTestId('ontology-name').textContent)
  expect(rows).toEqual(['SULO', 'Gene Ontology'])  // SULO 75% < GO 100%

  await user.click(labelHeader) // descending
  rows = screen.getAllByTestId('coverage-row').map(r => within(r).getByTestId('ontology-name').textContent)
  expect(rows).toEqual(['Gene Ontology', 'SULO'])
})

test('renders em-dash for zero-total cells', async () => {
  wrap(<Coverage />)
  await screen.findByText('Gene Ontology')
  // Individuals column for GO has total=0 → should render "—" not "NaN%"
  const goRow = screen.getAllByTestId('coverage-row')[0]
  expect(within(goRow).getByTestId('individuals-label-pct').textContent).toBe('—')
})
