/** The AI Assistant (chat, PDF/PowerPoint/Word/Excel/CSV, resume ATS, compare, analyse, images). It is its own small app that runs in the browser too. */
export default function AssistantFrame() {
  return <iframe className="assistant-frame" title="AI Assistant" src="assistant/index.html" allow="clipboard-read; clipboard-write" />;
}
