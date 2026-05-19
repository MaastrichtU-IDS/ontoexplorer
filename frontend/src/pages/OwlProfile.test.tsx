import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import OwlProfile from './OwlProfile'

const FLEET = {
  totals: {
    fleet_size: 2,
    el_count: 1,
    rl_count: 0,
    ql_count: 0,
    dl_count: 2,
  },
  ontologies: [
    {
      id: 'o1',
      shortname: 'go',
      title: 'Gene Ontology',
      version_id: 'v1',
      in_el: true,
      in_rl: false,
      in_ql: false,
      in_dl: true,
      el_violations: 0,
      rl_violations: 3,
      ql_violations: 10,
      dl_violations: 0,
    },
    {
      id: 'o2',
      shortname: 'sulo',
      title: 'SULO',
      version_id: 'v2',
      in_el: false,
      in_rl: false,
      in_ql: false,
      in_dl: true,
      el_violations: 5,
      rl_violations: 8,
      ql_violations: 12,
      dl_violations: 0,
    },
  ],
}

vi.mock('../lib/api', () => ({
  api: { owl_profile: { fleet: () => Promise.resolve(FLEET) } },
  slugFromIri: (iri: string) => iri.split(/[/#]/).pop() ?? iri,
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('renders fleet table with ontology names', async () => {
  wrap(<OwlProfile />)
  expect(await screen.findByText('Gene Ontology')).toBeInTheDocument()
  expect(screen.getByText('SULO')).toBeInTheDocument()
})

test('summary cards show correct counts from totals', async () => {
  wrap(<OwlProfile />)
  await screen.findByText('Gene Ontology')
  // EL: 1 / 2, RL: 0 / 2, QL: 0 / 2, DL: 2 / 2
  expect(screen.getByTestId('summary-el').textContent).toMatch(/1/)
  expect(screen.getByTestId('summary-el').textContent).toMatch(/2/)
  expect(screen.getByTestId('summary-dl').textContent).toMatch(/2/)
})

test('filter pill shows only EL-conformant ontologies', async () => {
  const user = userEvent.setup()
  wrap(<OwlProfile />)
  await screen.findByText('Gene Ontology')

  // Click the EL filter pill
  await user.click(screen.getByTestId('filter-el'))

  // Only Gene Ontology is EL-conformant; SULO is not
  expect(screen.getByText('Gene Ontology')).toBeInTheDocument()
  expect(screen.queryByText('SULO')).not.toBeInTheDocument()
})

test('sortable table sorts by ontology name', async () => {
  const user = userEvent.setup()
  wrap(<OwlProfile />)
  await screen.findByText('Gene Ontology')

  // Default sort is ascending by name → Gene Ontology before SULO
  const rows = screen.getAllByTestId('owl-profile-row')
  expect(rows[0].textContent).toMatch(/Gene Ontology/)
  expect(rows[1].textContent).toMatch(/SULO/)

  // Click "Ontology" header to sort descending
  await user.click(screen.getByTestId('sort-name'))
  const rows2 = screen.getAllByTestId('owl-profile-row')
  expect(rows2[0].textContent).toMatch(/SULO/)
  expect(rows2[1].textContent).toMatch(/Gene Ontology/)
})
