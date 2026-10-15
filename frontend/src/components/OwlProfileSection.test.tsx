import { render, screen, within, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import userEvent from '@testing-library/user-event'
import OwlProfileSection from './OwlProfileSection'

const RECORD = {
  indexed_at: '2026-05-19T10:00:00Z',
  el: {
    in_profile: true,
    total_violations: 0,
    violations_by_axiom_type: {},
    sample_violations: [],
  },
  rl: {
    in_profile: false,
    total_violations: 3,
    violations_by_axiom_type: { 'owl:hasSelf': 2, 'owl:oneOf': 1 },
    sample_violations: [
      {
        axiom_type: 'owl:hasSelf',
        subject_iri: 'http://example.org/A',
        manchester: [
          { t: 'iri', label: 'A', iri: 'http://example.org/A', in_ontology: true },
          { t: 'text', v: ' hasSelf ' },
          { t: 'text', v: 'true' },
        ],
      },
      { axiom_type: 'owl:hasSelf', subject_iri: 'http://example.org/B' },
      { axiom_type: 'owl:oneOf',   subject_iri: 'http://example.org/C', manchester: null },
    ],
  },
  ql: {
    in_profile: false,
    total_violations: 5,
    violations_by_axiom_type: { 'owl:allValuesFrom': 5 },
    sample_violations: [
      {
        axiom_type: 'owl:allValuesFrom',
        subject_iri: 'http://example.org/D',
        details: 'Uses only restriction',
        // no manchester field — should fall back to details
      },
    ],
  },
  dl: {
    in_profile: true,
    total_violations: 0,
    violations_by_axiom_type: {},
    sample_violations: [],
  },
}

const NOT_FOUND_ERR = Object.assign(new Error('Not found'), { status: 404 })

// versionFn is a vi.fn() so individual tests can override via mockRejectedValueOnce
const versionFn = vi.fn(() => Promise.resolve(RECORD))

vi.mock('../lib/api', () => ({
  api: { owl_profile: { version: (...args: unknown[]) => (versionFn as any)(...args) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  versionFn.mockImplementation(() => Promise.resolve(RECORD))
})

test('renders four profile cards with in_profile status', async () => {
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1" />)
  // All four profile names should appear
  expect(await screen.findByTestId('profile-card-el')).toBeInTheDocument()
  expect(screen.getByTestId('profile-card-rl')).toBeInTheDocument()
  expect(screen.getByTestId('profile-card-ql')).toBeInTheDocument()
  expect(screen.getByTestId('profile-card-dl')).toBeInTheDocument()
  // EL and DL in profile → check marks
  expect(within(screen.getByTestId('profile-card-el')).getByTestId('profile-check')).toBeInTheDocument()
  expect(within(screen.getByTestId('profile-card-dl')).getByTestId('profile-check')).toBeInTheDocument()
  // RL and QL not in profile → X marks
  expect(within(screen.getByTestId('profile-card-rl')).getByTestId('profile-x')).toBeInTheDocument()
  expect(within(screen.getByTestId('profile-card-ql')).getByTestId('profile-x')).toBeInTheDocument()
})

test('renders 404 placeholder when API returns 404', async () => {
  versionFn.mockImplementationOnce(() => Promise.reject(NOT_FOUND_ERR))
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1-404" />)
  expect(await screen.findByText(/not yet computed/i)).toBeInTheDocument()
})

test('expanding non-conformant profile shows violations by axiom type', async () => {
  const user = userEvent.setup()
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1" />)
  await screen.findByTestId('profile-card-rl')

  // Click the expander for RL
  const rlExpander = screen.getByTestId('expander-rl')
  await user.click(rlExpander)

  // Violations section should appear
  const violationsSection = screen.getByTestId('violations-rl')
  expect(violationsSection).toBeInTheDocument()
  // The violation list (by axiom type) should show owl:hasSelf and owl:oneOf
  const violationsList = violationsSection.querySelector('ul')
  expect(violationsList?.textContent).toMatch(/owl:hasSelf/)
  expect(violationsList?.textContent).toMatch(/owl:oneOf/)
})

test('last computed footer renders formatted indexed_at', async () => {
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1" />)
  // The footer should show the date
  expect(await screen.findByTestId('last-computed')).toBeInTheDocument()
  const footer = screen.getByTestId('last-computed').textContent || ''
  expect(footer).toMatch(/2026/)
})

test('last computed footer shows "unknown" (not "Invalid Date") when indexed_at is missing', async () => {
  // Older cached owl_profile payloads were written without indexed_at.
  const { indexed_at: _omit, ...noDate } = RECORD
  // Cast: at runtime the payload genuinely lacks indexed_at (the bug under test);
  // the mock's inferred type still expects the full record.
  versionFn.mockImplementation(() => Promise.resolve(noDate as typeof RECORD))
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1" />)
  const footer = await screen.findByTestId('last-computed')
  expect(footer.textContent || '').toMatch(/unknown/)
  expect(footer.textContent || '').not.toMatch(/Invalid Date/)
})

// The per-instance "sample violations" table was removed (issue #359): it was
// noisy and only a capped sample. The violations-by-axiom-type histogram remains
// (asserted above); full per-entity detail moves to the maintainer full-report
// command (below).

test('full-report command is hidden for non-maintainers', async () => {
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1" />)
  await screen.findByTestId('last-computed')
  expect(screen.queryByTestId('full-report-command')).toBeNull()
})

test('full-report command is shown to maintainers with the pinned image tag', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true, json: () => Promise.resolve({ git_ref: '0.4.153', version: '0.3.97' }),
  }))
  wrap(<OwlProfileSection ontologyId="o1" versionId="v1" canEdit />)
  const block = await screen.findByTestId('full-report-command')
  await waitFor(() => expect(block.textContent).toMatch(/ontoexplorer-api:0\.4\.153/))
  expect(block.textContent).toMatch(/owl_profile\.detect/)
  vi.restoreAllMocks()
})
