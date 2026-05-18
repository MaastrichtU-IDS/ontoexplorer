import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Compare from './Compare'

const PIZZA = {
  id: 'pizza-ont-id',
  iri: 'https://w3id.org/ontostart/pizza/',
  shortname: 'pizza',
  title: null,
  groups: [],
  auto_sync: false,
  created_at: '2026-05-17T00:00:00Z',
}
const PRO = {
  id: 'pro-ont-id',
  iri: 'https://w3id.org/ontostart/pro/',
  shortname: 'pro',
  title: null,
  groups: [],
  auto_sync: false,
  created_at: '2026-05-17T00:00:00Z',
}

const PIZZA_V_LATEST = {
  id: 'pizza-v-latest',
  ontology_id: PIZZA.id,
  version_iri: 'https://w3id.org/ontostart/pizza/0.0.12',
  format: 'nt',
  status: 'ready',
  sha256: 'abc',
  triple_count: 1483,
  download_url: '/download/pizza-latest',
  created_at: '2026-05-17T00:00:00Z',
}
const PIZZA_V_PREV = {
  id: 'pizza-v-prev',
  ontology_id: PIZZA.id,
  version_iri: 'https://w3id.org/ontostart/pizza/0.0.11',
  format: 'owl',
  status: 'ready',
  sha256: 'def',
  triple_count: 1483,
  download_url: '/download/pizza-prev',
  created_at: '2026-05-16T00:00:00Z',
}
const PRO_V_LATEST = {
  id: 'pro-v-latest',
  ontology_id: PRO.id,
  version_iri: 'https://w3id.org/ontostart/pro/0.0.4',
  format: 'ttl',
  status: 'ready',
  sha256: 'ghi',
  triple_count: 5000,
  download_url: '/download/pro-latest',
  created_at: '2026-05-17T00:00:00Z',
}

vi.mock('../lib/api', () => ({
  api: {
    ontologies: {
      list: () => Promise.resolve({ ontologies: [PIZZA, PRO] }),
      versions: (id: string) => {
        if (id === PIZZA.id) return Promise.resolve({ versions: [PIZZA_V_LATEST, PIZZA_V_PREV] })
        if (id === PRO.id) return Promise.resolve({ versions: [PRO_V_LATEST] })
        return Promise.resolve({ versions: [] })
      },
    },
    compare: {
      // Default to "not yet computed" (404 → synthetic pending in the hook).
      // Individual tests can override via .mockResolvedValueOnce(...) if needed.
      get: vi.fn(() => Promise.reject(new Error('Request failed: 404'))),
      compute: vi.fn(() => Promise.resolve({ status: 'pending' })),
    },
  },
}))

function wrap(ui: React.ReactElement, initialEntries: string[] = ['/compare']) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={initialEntries}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

test('Compare page renders both ontology pickers with a disabled compare button', async () => {
  wrap(<Compare />)
  expect(screen.getByText('Compare ontologies')).toBeInTheDocument()
  // Two picker buttons labeled "Select an ontology…" (one per side)
  const placeholderButtons = await screen.findAllByText('Select an ontology…')
  expect(placeholderButtons).toHaveLength(2)
  // Compare button starts disabled
  const compareButton = screen.getByRole('button', { name: /^Compare$/ })
  expect(compareButton).toBeDisabled()
})

test('picking both ontologies enables the Compare button after versions auto-default', async () => {
  wrap(<Compare />)
  // Open the From picker (first one in the document)
  const pickerButtons = await screen.findAllByText('Select an ontology…')
  fireEvent.click(pickerButtons[0])
  // The dropdown list shows both ontologies; pick pizza
  fireEvent.click(await screen.findByText('pizza'))
  // Open the To picker (now the only "Select an ontology…" button)
  fireEvent.click(screen.getByText('Select an ontology…'))
  fireEvent.click(await screen.findByText('pro'))

  // After versions load and auto-default, the Compare button becomes enabled.
  await waitFor(() => {
    expect(screen.getByRole('button', { name: /^Compare$/ })).toBeEnabled()
  })
})
