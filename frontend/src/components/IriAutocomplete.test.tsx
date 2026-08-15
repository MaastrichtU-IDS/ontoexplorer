import { useState } from 'react'
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import IriAutocomplete from './IriAutocomplete'

const { mockAuto } = vi.hoisted(() => ({
  mockAuto: vi.fn().mockResolvedValue({
    completions: [
      { text: 'Animal', type: 'class', iri: 'http://ex/Animal', short: 'ex:Animal', insert: '' },
      { text: 'Antelope', type: 'class', iri: 'http://ex/Antelope', short: 'ex:Antelope', insert: '' },
    ],
    context: '', replace_from: 0, replace_to: 0,
  }),
}))

vi.mock('../lib/api', () => ({ api: { ontologies: { autocomplete: mockAuto } } }))

function Harness({ onPick }: { onPick: (v: string) => void }) {
  const [v, setV] = useState('')
  return (
    <IriAutocomplete ontologyId="o1" versionId="v1" value={v}
      onChange={x => { setV(x); onPick(x) }} placeholder="cls" />
  )
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('IriAutocomplete', () => {
  it('suggests entities on ≥2 chars and inserts the full IRI on select', async () => {
    const onPick = vi.fn()
    wrap(<Harness onPick={onPick} />)
    const input = screen.getByPlaceholderText('cls')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'An' } })

    const option = await screen.findByText('Animal')
    fireEvent.mouseDown(option)

    await waitFor(() => expect(onPick).toHaveBeenCalledWith('http://ex/Animal'))
    expect(mockAuto).toHaveBeenCalledWith('o1', 'v1', 'An')
  })

  it('does not query for fewer than 2 characters', async () => {
    mockAuto.mockClear()
    wrap(<Harness onPick={vi.fn()} />)
    const input = screen.getByPlaceholderText('cls')
    fireEvent.focus(input)
    fireEvent.change(input, { target: { value: 'A' } })
    // give the debounce time to (not) fire
    await new Promise(r => setTimeout(r, 300))
    expect(mockAuto).not.toHaveBeenCalled()
  })
})
