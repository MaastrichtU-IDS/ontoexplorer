import { Link, useNavigate } from 'react-router-dom'
import AddOntologyForm from '../components/AddOntologyForm'

export default function AddOntology() {
  const navigate = useNavigate()
  return (
    <div style={{ maxWidth: 640 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
        <h1 style={{ fontSize: '1.1rem', fontWeight: 700 }}>Add Ontology</h1>
        <Link to="/dashboard" style={{ color: 'var(--text-muted)', fontSize: 'var(--font-size-sm)' }}>
          ← My ontologies
        </Link>
      </div>
      <p style={{ color: 'var(--text-dim)', fontSize: 'var(--font-size-sm)', marginBottom: '1rem' }}>
        Submit by IRI/URL, file upload, or pasted RDF. We'll track the outcome on a
        submission page you can return to any time.
      </p>
      {/* On submit, hand off to the durable submission record rather than polling
          inline — tracking then survives navigating away. */}
      <AddOntologyForm onQueued={(taskId) => navigate(`/dashboard/submissions/${taskId}`)} />
    </div>
  )
}
