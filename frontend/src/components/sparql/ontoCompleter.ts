import { api, Ontology } from '../../lib/api'
import { extractBaseIri } from './prefixUtils'
import { classifyPosition } from './positionUtils'

interface YasqeLike {
  getCompleteToken: () => { string: string; type: string | null }
  getPrefixesFromQuery: () => Record<string, string>
}

interface CompleterConfig {
  name: string
  bulk: boolean
  autoShow: boolean
  isValidCompletionPosition: (yasqe: YasqeLike) => boolean
  get: (yasqe: YasqeLike, token: { string: string; type: string | null }) => Promise<string[]>
}

/**
 * Build a Yasqe autocompleter that suggests IRIs/CURIEs from OntoExplorer's
 * search backend, scoped to the user's current ontology selection.
 *
 * @param getSelectedOntologyIds  closure read on each keystroke — returns the
 *                                ScopeToolbar's current selection.
 * @param getOntologies           closure that returns the full ontology list
 *                                (needed to map prefix → ontology id for
 *                                CURIE-position scoping).
 */
export function buildOntoCompleter(
  getSelectedOntologyIds: () => string[],
  getOntologies: () => Ontology[],
): CompleterConfig {
  return {
    name: 'ontoexplorer',
    bulk: false,
    autoShow: true,

    isValidCompletionPosition(yasqe) {
      const token = yasqe.getCompleteToken()
      const pos = classifyPosition(token, yasqe.getPrefixesFromQuery())
      return pos.kind !== 'none'
    },

    async get(yasqe, _token) {
      const token = yasqe.getCompleteToken()
      const prefixes = yasqe.getPrefixesFromQuery()
      const pos = classifyPosition(token, prefixes)
      if (pos.kind === 'none') return []

      const selected = getSelectedOntologyIds()
      let ontologyIds: string[] = selected
      const partial = pos.partial

      if (pos.kind === 'curie' && pos.baseIri) {
        // Restrict to the ontology that owns this prefix's base IRI, if known.
        const match = getOntologies().find(o => extractBaseIri(o.iri) === pos.baseIri)
        ontologyIds = match ? [match.id] : []
      } else if (pos.kind === 'curie' && !pos.baseIri) {
        // Unknown prefix in the editor — fall back to fleet-wide.
        ontologyIds = []
      }

      try {
        const resp = await api.globalSearch.autocomplete(partial, -1, ontologyIds)
        return resp.completions
          .filter(c => c.iri)
          .map(c => formatInsertion(c.iri as string, pos))
      } catch {
        return []
      }
    },
  }
}

/**
 * Format an IRI suggestion for insertion based on cursor position.
 * - `iri`   → `<full-iri>`
 * - `curie` → `prefix:LocalName` (using the prefix that was already typed)
 */
function formatInsertion(
  iri: string,
  pos: ReturnType<typeof classifyPosition>,
): string {
  if (pos.kind === 'iri') {
    return `<${iri}>`
  }
  if (pos.kind === 'curie' && pos.baseIri && iri.startsWith(pos.baseIri)) {
    const localName = iri.slice(pos.baseIri.length)
    return `${pos.prefix}:${localName}`
  }
  // Fallback: wrap in <> if we can't compose a CURIE
  return `<${iri}>`
}
