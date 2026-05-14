import { useState } from 'react'
import { useOntologyProfile, useProfileCandidates, usePatchProfile, useDetectProfile } from '../hooks/useOntologyProfile'

const CURATED_LABELS: Record<string, string> = {
  'http://www.w3.org/2000/01/rdf-schema#label': 'rdfs:label',
  'http://www.w3.org/2004/02/skos/core#prefLabel': 'skos:prefLabel',
  'http://purl.org/dc/terms/title': 'dcterms:title',
  'http://purl.org/dc/elements/1.1/title': 'dc:title',
  'https://schema.org/name': 'schema:name',
  'http://purl.obolibrary.org/obo/IAO_0000115': 'IAO:0000115',
  'http://www.w3.org/2004/02/skos/core#definition': 'skos:definition',
  'http://www.w3.org/2000/01/rdf-schema#comment': 'rdfs:comment',
  'http://purl.org/dc/terms/description': 'dcterms:description',
  'http://www.w3.org/2004/02/skos/core#altLabel': 'skos:altLabel',
  'http://www.geneontology.org/formats/oboInOwl#hasExactSynonym': 'oboInOwl:hasExactSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasRelatedSynonym': 'oboInOwl:hasRelatedSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasBroadSynonym': 'oboInOwl:hasBroadSynonym',
  'http://www.geneontology.org/formats/oboInOwl#hasNarrowSynonym': 'oboInOwl:hasNarrowSynonym',
  'http://www.w3.org/2002/07/owl#deprecated': 'owl:deprecated',
}

function shortIri(iri: string): string {
  return CURATED_LABELS[iri] ?? iri.split(/[/#]/).pop() ?? iri
}

function PropChip({ iri, count, onRemove }: { iri: string; count?: number; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: 'var(--bg)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '2px 6px', fontSize: 11, color: 'var(--text)',
    }}>
      <span title={iri}>{shortIri(iri)}</span>
      {count !== undefined && (
        <span style={{ color: 'var(--text-dim)', fontSize: 10 }}>({count.toLocaleString()})</span>
      )}
      <button
        onClick={onRemove}
        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-dim)', fontSize: 11, padding: 0 }}
      >
        ×
      </button>
    </span>
  )
}

function RoleSection({
  label, props, candidates, onRemove, onAdd,
}: {
  label: string
  props: string[]
  candidates: { iri: string; count: number }[]
  onRemove: (iri: string) => void
  onAdd: (iri: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [custom, setCustom] = useState('')

  const countMap = Object.fromEntries(candidates.map(c => [c.iri, c.count]))
  const available = candidates.map(c => c.iri).filter(iri => !props.includes(iri))

  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 6 }}>
        {label}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
        {props.length === 0 && (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>(none)</span>
        )}
        {props.map(iri => (
          <PropChip key={iri} iri={iri} count={countMap[iri]} onRemove={() => onRemove(iri)} />
        ))}
        <button
          onClick={() => setAdding(a => !a)}
          style={{
            fontSize: 10, padding: '2px 6px', borderRadius: 4,
            border: '1px dashed var(--border)', background: 'none',
            color: 'var(--accent)', cursor: 'pointer',
          }}
        >
          + Add
        </button>
      </div>
      {adding && (
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', paddingLeft: 4 }}>
          {available.map(iri => (
            <button
              key={iri}
              onClick={() => { onAdd(iri); setAdding(false) }}
              style={{
                fontSize: 10, padding: '2px 6px', borderRadius: 4,
                border: '1px solid var(--border)', background: 'var(--bg-secondary)',
                color: 'var(--text-muted)', cursor: 'pointer',
              }}
            >
              {shortIri(iri)} ({countMap[iri] ?? 0})
            </button>
          ))}
          <input
            value={custom}
            onChange={e => setCustom(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && custom.trim()) {
                onAdd(custom.trim())
                setCustom('')
                setAdding(false)
              }
            }}
            placeholder="Custom IRI…"
            style={{
              fontSize: 10, padding: '2px 6px', borderRadius: 4,
              border: '1px solid var(--border)', background: 'var(--bg)',
              color: 'var(--text)', width: 160,
            }}
          />
        </div>
      )}
    </div>
  )
}

export default function ProfileEditor({ ontologyId, versionId }: {
  ontologyId: string
  versionId: string
}) {
  const { data: profile, isLoading: profileLoading } = useOntologyProfile(ontologyId, versionId)
  const { data: candidates, isLoading: candidatesLoading } = useProfileCandidates(ontologyId, versionId)
  const patch = usePatchProfile(ontologyId, versionId)
  const detect = useDetectProfile(ontologyId, versionId)

  const [labelProps, setLabelProps] = useState<string[] | null>(null)
  const [definitionProps, setDefinitionProps] = useState<string[] | null>(null)
  const [synonymProps, setSynonymProps] = useState<string[] | null>(null)
  const [deprecatedProps, setDeprecatedProps] = useState<string[] | null>(null)

  if (profileLoading || candidatesLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>Loading profile…</div>
  }

  if (!profile) {
    return (
      <div style={{ padding: '1rem' }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 12 }}>
          No profile detected yet.
        </div>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{
            padding: '6px 14px', borderRadius: 4, border: 'none',
            background: 'var(--accent)', color: '#000', fontSize: 12, cursor: 'pointer',
          }}
        >
          {detect.isPending ? 'Running…' : 'Detect Profile'}
        </button>
      </div>
    )
  }

  const current = {
    label_props: labelProps ?? profile.label_props,
    definition_props: definitionProps ?? profile.definition_props,
    synonym_props: synonymProps ?? profile.synonym_props,
    deprecated_props: deprecatedProps ?? profile.deprecated_props,
  }

  const cand = candidates ?? { label: [], definition: [], synonym: [], deprecated: [], unknown: [], version_id: versionId }
  const isDirty = labelProps !== null || definitionProps !== null || synonymProps !== null || deprecatedProps !== null

  return (
    <div style={{ padding: '12px 16px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{
          fontSize: 10, padding: '1px 8px', borderRadius: 10,
          background: profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.1)' : 'rgba(88,166,255,0.1)',
          color: profile.status === 'user_confirmed' ? '#3fb950' : '#58a6ff',
          border: `1px solid ${profile.status === 'user_confirmed' ? 'rgba(63,185,80,0.25)' : 'rgba(88,166,255,0.25)'}`,
        }}>
          {profile.status === 'user_confirmed' ? '● confirmed' : '⟳ auto-detected'}
        </span>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{ fontSize: 10, color: 'var(--text-dim)', background: 'none', border: 'none', cursor: 'pointer' }}
        >
          {detect.isPending ? 'Re-detecting…' : 'Re-detect'}
        </button>
      </div>

      <RoleSection
        label="Labels"
        props={current.label_props}
        candidates={cand.label}
        onRemove={iri => setLabelProps(current.label_props.filter(p => p !== iri))}
        onAdd={iri => setLabelProps([...current.label_props, iri])}
      />
      <RoleSection
        label="Definitions"
        props={current.definition_props}
        candidates={cand.definition}
        onRemove={iri => setDefinitionProps(current.definition_props.filter(p => p !== iri))}
        onAdd={iri => setDefinitionProps([...current.definition_props, iri])}
      />
      <RoleSection
        label="Synonyms"
        props={current.synonym_props}
        candidates={cand.synonym}
        onRemove={iri => setSynonymProps(current.synonym_props.filter(p => p !== iri))}
        onAdd={iri => setSynonymProps([...current.synonym_props, iri])}
      />
      <RoleSection
        label="Deprecated"
        props={current.deprecated_props}
        candidates={cand.deprecated}
        onRemove={iri => setDeprecatedProps(current.deprecated_props.filter(p => p !== iri))}
        onAdd={iri => setDeprecatedProps([...current.deprecated_props, iri])}
      />

      {cand.unknown.length > 0 && (
        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border)' }}>
          <div style={{ color: '#d29922', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 8 }}>
            Unknown Properties
          </div>
          {cand.unknown.map(u => (
            <div key={u.iri} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 11, color: 'var(--text-muted)', flex: 1 }} title={u.iri}>
                {shortIri(u.iri)}
                <span style={{ color: 'var(--text-dim)', fontSize: 10 }}> ({u.count.toLocaleString()} classes)</span>
              </span>
              {(['label', 'definition', 'synonym', 'deprecated'] as const).map(role => (
                <button
                  key={role}
                  onClick={() => {
                    const setters = {
                      label: setLabelProps,
                      definition: setDefinitionProps,
                      synonym: setSynonymProps,
                      deprecated: setDeprecatedProps,
                    }
                    const curr = {
                      label: current.label_props,
                      definition: current.definition_props,
                      synonym: current.synonym_props,
                      deprecated: current.deprecated_props,
                    }
                    setters[role]([...curr[role], u.iri])
                  }}
                  style={{
                    fontSize: 9, padding: '1px 5px', borderRadius: 3,
                    border: '1px solid var(--border)', background: 'none',
                    color: 'var(--text-dim)', cursor: 'pointer',
                  }}
                >
                  {role}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}

      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <button
          onClick={() => {
            patch.mutate({
              label_props: current.label_props,
              definition_props: current.definition_props,
              synonym_props: current.synonym_props,
              deprecated_props: current.deprecated_props,
            }, {
              onSuccess: () => {
                setLabelProps(null)
                setDefinitionProps(null)
                setSynonymProps(null)
                setDeprecatedProps(null)
              },
            })
          }}
          disabled={!isDirty || patch.isPending}
          style={{
            padding: '6px 16px', borderRadius: 4, border: 'none',
            background: isDirty ? 'var(--accent)' : 'var(--bg-secondary)',
            color: isDirty ? '#000' : 'var(--text-dim)',
            fontSize: 12, cursor: isDirty ? 'pointer' : 'default',
          }}
        >
          {patch.isPending ? 'Saving and re-indexing…' : 'Save and re-index'}
        </button>
        {patch.isSuccess && (
          <span style={{ marginLeft: 10, color: '#3fb950', fontSize: 11 }}>✓ Saved</span>
        )}
      </div>
    </div>
  )
}
