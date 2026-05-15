import { useState } from 'react'
import { useOntologyMeta, useMetaCandidates, usePatchMeta, useDetectMeta } from '../hooks/useOntologyMeta'
import { MetaProfilePatch } from '../lib/api'

const ROLE_LABELS: Record<string, string> = {
  title_props: 'Title',
  shortname_props: 'Shortname / Acronym',
  description_props: 'Description',
  creator_props: 'Creator',
  contributor_props: 'Contributor',
  publisher_props: 'Publisher',
  license_props: 'License',
  homepage_props: 'Homepage',
  version_info_props: 'Version Info',
  prefix_props: 'Namespace Prefix',
  namespace_uri_props: 'Namespace URI',
  created_props: 'Created',
  modified_props: 'Modified',
  language_props: 'Language',
  citation_props: 'Citation',
  funding_props: 'Funding',
  status_props: 'Status',
  syntax_props: 'Syntax',
}

const IRI_LABELS: Record<string, string> = {
  'http://purl.org/dc/terms/title': 'dcterms:title',
  'http://www.w3.org/2000/01/rdf-schema#label': 'rdfs:label',
  'http://purl.org/dc/elements/1.1/title': 'dc:title',
  'http://purl.org/dc/terms/alternative': 'dcterms:alternative',
  'http://www.w3.org/2002/07/owl#acronym': 'owl:acronym',
  'http://purl.org/vocab/vann/preferredNamespacePrefix': 'vann:preferredNamespacePrefix',
  'http://purl.org/dc/terms/description': 'dcterms:description',
  'http://www.w3.org/2000/01/rdf-schema#comment': 'rdfs:comment',
  'http://purl.org/dc/elements/1.1/description': 'dc:description',
  'http://purl.org/dc/terms/creator': 'dcterms:creator',
  'http://purl.org/dc/elements/1.1/creator': 'dc:creator',
  'http://purl.org/pav/authoredBy': 'pav:authoredBy',
  'http://purl.org/dc/terms/contributor': 'dcterms:contributor',
  'http://purl.org/dc/terms/publisher': 'dcterms:publisher',
  'http://purl.org/dc/terms/license': 'dcterms:license',
  'http://purl.org/dc/terms/rights': 'dcterms:rights',
  'http://xmlns.com/foaf/0.1/homepage': 'foaf:homepage',
  'http://www.w3.org/ns/dcat#accessURL': 'dcat:accessURL',
  'https://schema.org/includedInDataCatalog': 'schema:includedInDataCatalog',
  'http://www.w3.org/2002/07/owl#versionInfo': 'owl:versionInfo',
  'http://purl.org/vocab/vann/preferredNamespaceUri': 'vann:preferredNamespaceUri',
  'http://purl.org/dc/terms/created': 'dcterms:created',
  'http://purl.org/dc/terms/issued': 'dcterms:issued',
  'http://purl.org/dc/terms/modified': 'dcterms:modified',
  'http://purl.org/dc/terms/language': 'dcterms:language',
  'http://purl.org/dc/terms/bibliographicCitation': 'dcterms:bibliographicCitation',
  'https://schema.org/funding': 'schema:funding',
  'https://w3id.org/mod#status': 'mod:status',
  'https://w3id.org/mod#hasSyntax': 'mod:hasSyntax',
  'https://w3id.org/mod#hasRepresentationLanguage': 'mod:hasRepresentationLanguage',
}

const ALL_ROLE_COLS = Object.keys(ROLE_LABELS) as (keyof MetaProfilePatch)[]

function shortIri(iri: string): string {
  return IRI_LABELS[iri] ?? iri.split(/[/#]/).pop() ?? iri
}

function PropChip({
  iri, onRemove,
}: { iri: string; onRemove: () => void }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 4,
      background: 'var(--bg)', border: '1px solid var(--border)',
      borderRadius: 4, padding: '2px 6px', fontSize: 11, color: 'var(--text)',
    }}>
      <span title={iri}>{shortIri(iri)}</span>
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
  col, props, candidateIris, onRemove, onAdd,
}: {
  col: keyof MetaProfilePatch
  props: string[]
  candidateIris: string[]
  onRemove: (iri: string) => void
  onAdd: (iri: string) => void
}) {
  const [adding, setAdding] = useState(false)
  const [custom, setCustom] = useState('')
  const available = candidateIris.filter(iri => !props.includes(iri))

  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ color: 'var(--text-dim)', fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 5 }}>
        {ROLE_LABELS[col]}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 3 }}>
        {props.length === 0 && (
          <span style={{ color: 'var(--text-dim)', fontSize: 11 }}>(none)</span>
        )}
        {props.map(iri => (
          <PropChip key={iri} iri={iri} onRemove={() => onRemove(iri)} />
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
              {shortIri(iri)}
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

export default function MetaProfileEditor({
  ontologyId,
  versionId,
}: {
  ontologyId: string
  versionId: string
}) {
  const { data: profile, isLoading: profileLoading } = useOntologyMeta(ontologyId, versionId)
  const { data: candidates } = useMetaCandidates(ontologyId, versionId)
  const patch = usePatchMeta(ontologyId, versionId)
  const detect = useDetectMeta(ontologyId, versionId)

  const [edits, setEdits] = useState<Partial<MetaProfilePatch>>({})

  if (profileLoading) {
    return <div style={{ padding: '1rem', color: 'var(--text-dim)', fontSize: 12 }}>Loading…</div>
  }

  if (!profile) {
    return (
      <div style={{ padding: '1rem' }}>
        <div style={{ color: 'var(--text-dim)', fontSize: 12, marginBottom: 12 }}>
          No metadata profile detected yet.
        </div>
        <button
          onClick={() => detect.mutate()}
          disabled={detect.isPending}
          style={{
            padding: '6px 14px', borderRadius: 4, border: 'none',
            background: 'var(--accent)', color: '#000', fontSize: 12, cursor: 'pointer',
          }}
        >
          {detect.isPending ? 'Running…' : 'Detect Metadata'}
        </button>
      </div>
    )
  }

  const current = ALL_ROLE_COLS.reduce((acc, col) => {
    acc[col] = (edits[col] ?? (profile as any)[col]) as string[]
    return acc
  }, {} as Record<keyof MetaProfilePatch, string[]>)

  const candidatesByCol: Record<string, string[]> = {}
  for (const col of ALL_ROLE_COLS) {
    const role = col.replace(/_props$/, '')
    const roleData = (candidates as any)?.[role]
    candidatesByCol[col] = Array.isArray(roleData)
      ? roleData.map((c: { iri: string }) => c.iri)
      : []
  }

  const isDirty = Object.keys(edits).length > 0

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

      {ALL_ROLE_COLS.map(col => (
        <RoleSection
          key={col}
          col={col}
          props={current[col] ?? []}
          candidateIris={candidatesByCol[col] ?? []}
          onRemove={iri => setEdits(prev => ({ ...prev, [col]: (current[col] ?? []).filter(p => p !== iri) }))}
          onAdd={iri => setEdits(prev => ({ ...prev, [col]: [...(current[col] ?? []), iri] }))}
        />
      ))}

      <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
        <button
          onClick={() =>
            patch.mutate(
              ALL_ROLE_COLS.reduce((acc, col) => {
                acc[col] = current[col]
                return acc
              }, {} as MetaProfilePatch),
              { onSuccess: () => setEdits({}) }
            )
          }
          disabled={!isDirty || patch.isPending}
          style={{
            padding: '6px 16px', borderRadius: 4, border: 'none',
            background: isDirty ? 'var(--accent)' : 'var(--bg-secondary)',
            color: isDirty ? '#000' : 'var(--text-dim)',
            fontSize: 12, cursor: isDirty ? 'pointer' : 'default',
          }}
        >
          {patch.isPending ? 'Saving…' : 'Save and re-resolve'}
        </button>
        {patch.isSuccess && (
          <span style={{ marginLeft: 10, color: '#3fb950', fontSize: 11 }}>✓ Saved</span>
        )}
      </div>
    </div>
  )
}
