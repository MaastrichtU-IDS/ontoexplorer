import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { JobsTable } from './JobsTable'
import type { AdminJobEntry } from '../../lib/api'

function job(over: Partial<AdminJobEntry> = {}): AdminJobEntry {
  return {
    id: 'j1',
    type: 'reason',
    version_id: 'v1',
    ontology_shortname: 'go',
    ontology_iri: 'http://purl.obolibrary.org/obo/go.owl',
    status: 'done',
    started_at: '2026-08-20T10:00:00Z',
    finished_at: '2026-08-20T10:01:00Z',
    error: null,
    ...over,
  }
}

describe('JobsTable', () => {
  // The table showed a red row tint and a status dot for a failure but never
  // the reason, so the only account of *why* an ingestion failed lived in the
  // worker log. These rows are the sole UI trace of a submission that died
  // before producing a version.
  it('shows the error message for a failed job', () => {
    render(<JobsTable jobs={[job({
      type: 'ingestion',
      status: 'failed',
      version_id: null,
      ontology_shortname: null,
      ontology_iri: null,
      error: 'Response exceeds size limit (706398355 bytes, limit 536870912 bytes)',
    })]} />)

    expect(screen.getByText(/exceeds size limit/)).toBeInTheDocument()
  })

  it('renders a version-less ingestion row without an ontology label', () => {
    render(<JobsTable jobs={[job({
      type: 'ingestion',
      status: 'failed',
      version_id: null,
      ontology_shortname: null,
      ontology_iri: null,
      error: 'boom',
    })]} />)

    expect(screen.getByText('ingestion')).toBeInTheDocument()
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  it('shows no error row for a successful job', () => {
    render(<JobsTable jobs={[job()]} />)
    expect(screen.queryByText(/exceeds size limit/)).not.toBeInTheDocument()
  })
})
