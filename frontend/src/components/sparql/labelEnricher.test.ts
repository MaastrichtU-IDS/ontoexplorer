import { describe, it, expect, beforeEach } from 'vitest'
import { collectIris, buildLabelsQuery, applyLabels, removeLabels } from './labelEnricher'

function makeTable(hrefs: string[]): HTMLElement {
  const root = document.createElement('div')
  root.innerHTML = `
    <table>
      <tbody>
        ${hrefs.map(h => `<tr><td><span><a class="iri" href="${h}">${h}</a></span></td></tr>`).join('')}
      </tbody>
    </table>
  `
  return root
}

describe('collectIris', () => {
  it('returns empty array when no a.iri present', () => {
    const root = document.createElement('div')
    expect(collectIris(root)).toEqual([])
  })

  it('extracts hrefs from a.iri elements', () => {
    const root = makeTable(['http://a/', 'http://b/'])
    expect(collectIris(root)).toEqual(['http://a/', 'http://b/'])
  })

  it('deduplicates repeated IRIs', () => {
    const root = makeTable(['http://a/', 'http://a/', 'http://b/'])
    expect(collectIris(root)).toEqual(['http://a/', 'http://b/'])
  })

  it('ignores anchors without the iri class', () => {
    const root = document.createElement('div')
    root.innerHTML = `<a href="http://x/">x</a><a class="iri" href="http://y/">y</a>`
    expect(collectIris(root)).toEqual(['http://y/'])
  })
})

describe('buildLabelsQuery', () => {
  it('returns empty string for empty list', () => {
    expect(buildLabelsQuery([])).toBe('')
  })

  it('builds a VALUES + rdfs:label SELECT for one IRI', () => {
    expect(buildLabelsQuery(['http://a/foo'])).toBe(
      'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n' +
      'SELECT ?iri ?label WHERE {\n' +
      '  VALUES ?iri { <http://a/foo> }\n' +
      '  ?iri rdfs:label ?label .\n' +
      '}'
    )
  })

  it('joins multiple IRIs in the VALUES block', () => {
    const q = buildLabelsQuery(['http://a/', 'http://b/'])
    expect(q).toContain('VALUES ?iri { <http://a/> <http://b/> }')
  })
})

describe('applyLabels', () => {
  beforeEach(() => { document.body.innerHTML = '' })

  it('appends an iri-label span after each matching a.iri', () => {
    const root = makeTable(['http://a/', 'http://b/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha'], ['http://b/', 'Beta']]))
    const spans = root.querySelectorAll('.iri-label')
    expect(spans.length).toBe(2)
    expect(spans[0].textContent).toBe(' · Alpha')
    expect(spans[1].textContent).toBe(' · Beta')
  })

  it('skips IRIs absent from the label map', () => {
    const root = makeTable(['http://a/', 'http://nolabel/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha']]))
    expect(root.querySelectorAll('.iri-label').length).toBe(1)
  })

  it('does not duplicate spans on repeated calls', () => {
    const root = makeTable(['http://a/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha']]))
    applyLabels(root, new Map([['http://a/', 'Alpha']]))
    expect(root.querySelectorAll('.iri-label').length).toBe(1)
  })
})

describe('removeLabels', () => {
  it('removes every .iri-label span', () => {
    const root = makeTable(['http://a/', 'http://b/'])
    document.body.appendChild(root)
    applyLabels(root, new Map([['http://a/', 'Alpha'], ['http://b/', 'Beta']]))
    expect(root.querySelectorAll('.iri-label').length).toBe(2)
    removeLabels(root)
    expect(root.querySelectorAll('.iri-label').length).toBe(0)
  })

  it('is a no-op when no labels are present', () => {
    const root = makeTable(['http://a/'])
    document.body.appendChild(root)
    expect(() => removeLabels(root)).not.toThrow()
  })
})
