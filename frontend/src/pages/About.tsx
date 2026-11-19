import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import MarkdownPage from '../components/MarkdownPage'
import aboutMd from '../content/about.md?raw'

// `{{nOnt}}` in the copy is filled with the live catalogue count.
export default function About() {
  const { data } = useQuery({ queryKey: ['public-stats'], queryFn: () => api.stats.public() })
  const nOnt = data?.total_ontologies != null ? data.total_ontologies.toLocaleString() : 'many'
  return <MarkdownPage source={aboutMd} substitutions={{ nOnt }} />
}
