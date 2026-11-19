import MarkdownPage from '../components/MarkdownPage'
import contactMd from '../content/contact.md?raw'

export default function Contact() {
  return <MarkdownPage source={contactMd} />
}
