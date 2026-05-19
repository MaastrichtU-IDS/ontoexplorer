import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ManchesterFrame from './ManchesterFrame'
import type { ManchesterFrame as Frame } from '../lib/api'

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter>{ui}</MemoryRouter>)
}

const PIZZA = 'http://example.org/Pizza'
const FOOD  = 'http://example.org/Food'
const EXTERNAL = 'http://other.org/ExternalThing'

const frame: Frame = {
  lines: [
    {
      op: null,
      tokens: [
        { t: 'text', v: 'Class: ' },
        { t: 'iri', label: 'Pizza', iri: PIZZA, in_ontology: true },
        { t: 'text', v: `  (${PIZZA})` },
      ],
    },
    {
      op: null,
      tokens: [{ t: 'text', v: '    SubClassOf:' }],
    },
    {
      op: 'added',
      tokens: [
        { t: 'text', v: '        ' },
        { t: 'iri', label: 'Food', iri: FOOD, in_ontology: true },
      ],
    },
    {
      op: 'removed',
      tokens: [
        { t: 'text', v: '        ' },
        { t: 'iri', label: 'External', iri: EXTERNAL, in_ontology: false },
      ],
    },
  ],
}

test('in_ontology=true tokens render as Link with href and tooltip', () => {
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  const link = screen.getByRole('link', { name: 'Pizza' })
  expect(link).toHaveAttribute('href', `/ontologies/pizza?term=${encodeURIComponent(PIZZA)}`)
  expect(link).toHaveAttribute('title', PIZZA)
})

test('in_ontology=false tokens render as plain span with tooltip only (no link)', () => {
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  const external = screen.getByText('External')
  expect(external.tagName).toBe('SPAN')
  expect(external).toHaveAttribute('title', EXTERNAL)
  expect(external).not.toHaveAttribute('href')
})

test('shortname=null disables linking even for in_ontology tokens', () => {
  wrap(<ManchesterFrame frame={frame} shortname={null} />)
  expect(screen.queryByRole('link')).toBeNull()
  const pizza = screen.getByText('Pizza')
  expect(pizza.tagName).toBe('SPAN')
})

test('added/removed lines use respective color and line marker', () => {
  wrap(<ManchesterFrame frame={frame} shortname="pizza" />)
  const addedFood = screen.getByText('Food')
  const addedLine = addedFood.closest('div')!
  expect(addedLine.style.color).toBe('rgb(63, 185, 80)')   // #3fb950
  expect(addedLine.textContent?.startsWith('+ ')).toBe(true)

  const removedExternal = screen.getByText('External')
  const removedLine = removedExternal.closest('div')!
  expect(removedLine.style.color).toBe('rgb(248, 81, 73)')  // #f85149
  expect(removedLine.textContent?.startsWith('- ')).toBe(true)
})
