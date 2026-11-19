import MarkdownPage from '../components/MarkdownPage'
import privacyMd from '../content/privacy.md?raw'

export default function Privacy() {
  return <MarkdownPage source={privacyMd} />
}
