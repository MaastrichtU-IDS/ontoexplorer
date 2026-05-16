import { useEffect, useRef } from 'react'
import Yasgui from '@triply/yasgui'
import '@triply/yasgui/build/yasgui.min.css'

const DEFAULT_QUERY = `PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?class ?label WHERE {
  ?class a owl:Class .
  OPTIONAL { ?class rdfs:label ?label }
}
LIMIT 100`

export default function Sparql() {
  const containerRef = useRef<HTMLDivElement>(null)
  const yasguiRef = useRef<InstanceType<typeof Yasgui> | null>(null)

  useEffect(() => {
    if (!containerRef.current || yasguiRef.current) return

    yasguiRef.current = new Yasgui(containerRef.current, {
      persistenceId: null,
      requestConfig: {
        endpoint: '/api/v1/sparql/content',
        method: 'POST',
        acceptHeaderSelect: 'application/sparql-results+json',
        acceptHeaderGraph: 'text/turtle',
      },
      endpointCatalogueOptions: {
        getData: () => [
          { endpoint: '/api/v1/sparql/content', title: 'OntoExplorer — Ontology Content' },
        ],
      },
    })
    // Set initial query via the API (avoids type-unsafe 'as any' cast on yasqe config)
    yasguiRef.current.getTab()?.getYasqe()?.setValue(DEFAULT_QUERY)

    return () => {
      if (yasguiRef.current) {
        if (typeof yasguiRef.current.destroy === 'function') {
          yasguiRef.current.destroy()
        } else if (containerRef.current) {
          containerRef.current.innerHTML = ''
        }
        yasguiRef.current = null
      }
    }
  }, [])

  return (
    <div style={{
      height: 'calc(100vh - var(--nav-height))',
      display: 'flex',
      flexDirection: 'column',
      overflow: 'hidden',
    }}>
      <div ref={containerRef} style={{ flex: 1, minHeight: 0 }} />
    </div>
  )
}
