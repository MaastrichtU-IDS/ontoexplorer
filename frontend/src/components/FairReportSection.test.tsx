import { render, screen, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FairReportSection from './FairReportSection'

const REPORT = {
  overall: 0.95, overall_pct: 95, verdict: 'Strong FAIRness',
  n_checks: 19, n_passed: 18, ontology_id: 'o1', version_id: 'v1',
  principles: [
    {
      principle: 'F', score: 1, score_pct: 100, checks: [
        {
          id: 'F1', principle: 'F', name: 'Globally unique, stable identifier',
          status: 'pass', score: 1, score_pct: 100,
          evidence: 'Canonical ontology IRI present.', panel: 'identity',
          tests: [['Canonical ontology IRI', 'http://ex/o']], detail: null,
        },
      ],
    },
    {
      principle: 'R', score: 0.92, score_pct: 92, checks: [
        {
          id: 'R4', principle: 'R', name: 'Recommended metadata completeness',
          status: 'pass', score: 0.857, score_pct: 86,
          evidence: '18 of 21 scored roles filled (86%); 8 optional MOD roles excluded.',
          panel: 'metadata', tests: [],
          detail: {
            scored: 21, filled: 18, excluded: 8,
            roles: [
              { role: 'Title', predicates: ['dcterms:title'], filled: true, excluded: false },
              { role: 'Funding', predicates: ['schema:funding'], filled: false, excluded: false },
              { role: 'Competency question', predicates: ['mod:competencyQuestion'], filled: false, excluded: true },
            ],
          },
        },
        {
          id: 'R6', principle: 'R', name: 'Terms carry definitions',
          status: 'partial', score: 0.83, score_pct: 83,
          evidence: '83% have a definition.', panel: 'coverage',
          tests: [['Coverage', '2261 / 2724 = 83%']], detail: null,
        },
      ],
    },
  ],
}

const reportFn = vi.fn(() => Promise.resolve(REPORT))

vi.mock('../lib/api', () => ({
  api: { fair: { report: (...args: unknown[]) => (reportFn as any)(...args) } },
}))

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  reportFn.mockImplementation(() => Promise.resolve(REPORT))
})

test('renders overall score and verdict', async () => {
  wrap(<FairReportSection ontologyId="o1" versionId="v1" />)
  const overall = await screen.findByTestId('fair-overall')
  expect(within(overall).getByText('95')).toBeInTheDocument()
  expect(within(overall).getByText('Strong FAIRness')).toBeInTheDocument()
})

test('renders all principle groups and a partial check', async () => {
  wrap(<FairReportSection ontologyId="o1" versionId="v1" />)
  expect(await screen.findByTestId('fair-principle-F')).toBeInTheDocument()
  expect(screen.getByTestId('fair-principle-R')).toBeInTheDocument()
  const r6 = screen.getByTestId('fair-check-R6')
  expect(within(r6).getByText('Terms carry definitions')).toBeInTheDocument()
  expect(within(r6).getByLabelText('Partial')).toBeInTheDocument()
})

test('R4 expands to scored roles plus the excluded optional roles', async () => {
  wrap(<FairReportSection ontologyId="o1" versionId="v1" />)
  const r4 = await screen.findByTestId('fair-check-R4')
  // <details> children are in the DOM regardless of open state
  expect(within(r4).getByText('Title')).toBeInTheDocument()
  expect(within(r4).getByText('Funding')).toBeInTheDocument()
  expect(within(r4).getByText('Competency question')).toBeInTheDocument()
  expect(within(r4).getByText(/Optional — not scored \(1\)/)).toBeInTheDocument()
  expect(within(r4).getByText('dcterms:title')).toBeInTheDocument()
})

test('shows a placeholder when the report is not yet computed (404)', async () => {
  reportFn.mockImplementationOnce(() =>
    Promise.reject(Object.assign(new Error('Not found'), { status: 404 })))
  wrap(<FairReportSection ontologyId="o1" versionId="v404" />)
  expect(await screen.findByText(/not yet computed/i)).toBeInTheDocument()
})
