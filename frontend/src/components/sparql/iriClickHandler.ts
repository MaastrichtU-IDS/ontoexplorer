import { api, Ontology } from '../../lib/api'
import { findOwningOntology, termPageUrl } from './iriResolver'

interface InstallDeps {
  getOntologies: () => Ontology[]
  navigate: (path: string) => void
}

/**
 * Attach a single delegated click listener to `rootEl` that intercepts clicks
 * on `<a class="iri">` elements (rendered by Yasr's table plugin). The handler:
 *
 * 1. Skips modified clicks (Ctrl, Cmd, Shift, middle-mouse) so users keep
 *    "open in new tab" affordances.
 * 2. Tries a longest-prefix match against the current ontology selection.
 * 3. Falls back to `/api/v1/search?q=<iri>&mode=entity&limit=1` if no
 *    in-scope ontology matches.
 * 4. On miss / network error, calls `window.open(iri, '_blank')` so the user
 *    still reaches the raw IRI.
 *
 * Returns a teardown function that removes the listener.
 */
export function installIriClickHandler(rootEl: HTMLElement, deps: InstallDeps): () => void {
  function handler(event: MouseEvent) {
    if (event.ctrlKey || event.metaKey || event.shiftKey || event.button !== 0) return

    const target = event.target as Element | null
    if (!target) return
    const anchor = target.closest('a.iri') as HTMLAnchorElement | null
    if (!anchor) return

    const iri = anchor.getAttribute('href')
    if (!iri) return

    // Try in-scope prefix match first
    const owning = findOwningOntology(iri, deps.getOntologies())
    if (owning && owning.shortname) {
      event.preventDefault()
      deps.navigate(termPageUrl(owning.shortname, iri))
      return
    }

    // Fall back to search API
    event.preventDefault()
    api.globalSearch.search(iri, 1).then(
      resp => {
        const hit = resp.results?.[0]
        if (hit?.ontology_id) {
          const found = deps.getOntologies().find(o => o.id === hit.ontology_id)
          if (found?.shortname) {
            deps.navigate(termPageUrl(found.shortname, iri))
            return
          }
        }
        window.open(iri, '_blank')
      },
      () => {
        window.open(iri, '_blank')
      },
    )
  }

  rootEl.addEventListener('click', handler)
  return () => rootEl.removeEventListener('click', handler)
}
