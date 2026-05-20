/**
 * Collect unique hrefs from every `a.iri` descendant of `root`.
 */
export function collectIris(root: HTMLElement): string[] {
  const seen = new Set<string>()
  root.querySelectorAll<HTMLAnchorElement>('a.iri').forEach(a => {
    const href = a.getAttribute('href')
    if (href) seen.add(href)
  })
  return Array.from(seen)
}

/**
 * Build a VALUES-based SPARQL query that asks for rdfs:label for the given IRIs.
 * Returns the empty string when iris is empty.
 */
export function buildLabelsQuery(iris: string[]): string {
  if (iris.length === 0) return ''
  const values = iris.map(iri => `<${iri}>`).join(' ')
  return (
    'PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>\n' +
    'SELECT ?iri ?label WHERE {\n' +
    `  VALUES ?iri { ${values} }\n` +
    '  ?iri rdfs:label ?label .\n' +
    '}'
  )
}

/**
 * For each `a.iri` whose href is a key in `labels`, append a `<span class="iri-label">`
 * immediately after the anchor showing the label. Idempotent: re-applying with the
 * same data doesn't duplicate spans.
 */
export function applyLabels(root: HTMLElement, labels: Map<string, string>): void {
  root.querySelectorAll<HTMLAnchorElement>('a.iri').forEach(a => {
    const href = a.getAttribute('href') ?? ''
    const label = labels.get(href)
    if (!label) return
    // Skip if the next sibling is already our injected label span
    const next = a.nextElementSibling
    if (next && next.classList.contains('iri-label')) return
    const span = document.createElement('span')
    span.className = 'iri-label'
    span.style.color = 'var(--text-dim)'
    span.style.marginLeft = '4px'
    span.textContent = ` · ${label}`
    a.insertAdjacentElement('afterend', span)
  })
}

/**
 * Remove every `.iri-label` span beneath `root`.
 */
export function removeLabels(root: HTMLElement): void {
  root.querySelectorAll('.iri-label').forEach(el => el.remove())
}
