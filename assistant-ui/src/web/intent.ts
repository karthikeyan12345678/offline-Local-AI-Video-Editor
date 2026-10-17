// What the person asked for: a port of the desktop assistant's intent detection (backend/ltxps/assistant/service.py). No browser APIs here, so it can be tested in Node.
const FORMAT_WORDS: Record<string, string> = { pdf: "pdf", ppt: "pptx", pptx: "pptx", powerpoint: "pptx", slides: "pptx", slide: "pptx", deck: "pptx", presentation: "pptx", doc: "docx", docx: "docx", word: "docx", csv: "csv", xlsx: "xlsx", excel: "xlsx", spreadsheet: "xlsx" };
const COMMANDS: Record<string, string> = { pdf: "pdf", ppt: "pptx", pptx: "pptx", slides: "pptx", doc: "docx", docx: "docx", word: "docx", csv: "csv", xlsx: "xlsx", excel: "xlsx", ats: "ats", resume: "ats", image: "image", img: "image", draw: "image",
  compare: "compare", diff: "compare", analyze: "analyze", analyse: "analyze", analytics: "analyze", design: "design", theme: "design" };

export function detectIntent(text: string, nFiles: number): { kind: string; text: string } {
  const t = text.trim();
  const m = /^\/(\w+)\s*([\s\S]*)$/.exec(t);
  if (m && COMMANDS[m[1].toLowerCase()]) return { kind: COMMANDS[m[1].toLowerCase()], text: m[2].trim() };
  const low = t.toLowerCase();
  if (/\b(generate|create|make|draw|paint|render|produce)\b.{0,25}\b(image|picture|photo|illustration|logo|poster|artwork|wallpaper)\b/.test(low) && nFiles === 0) return { kind: "image", text: t };
  if (nFiles >= 2 && /\b(compare|difference|differences|diff|what changed|which is better)\b/.test(low)) return { kind: "compare", text: t };
  if (nFiles >= 1 && /\b(tailor|tailoring|customi[sz]e|optimi[sz]e|rewrite|rework|revamp|improve|update|fix|adapt|align|match)\b.{0,80}\b(resume|cv|pdf|doc|docx|file|jd|job description|ats)\b|\b(resume|cv)\b.{0,60}\b(jd|job description|ats|tailor)/.test(low)
    && /\b(tailor\w*|jd|job description|ats|job posting|role)\b/.test(low)) return { kind: "tailor", text: t };
  if (nFiles >= 1 && /\b(ats|resume score|resume check|check (my )?resume|applicant tracking)\b/.test(low)) return { kind: "ats", text: t };
  if (nFiles >= 1 && /\b(analy[sz]e|analytics|statistics|stats|profile this|summari[sz]e the data|insights?)\b/.test(low)) return { kind: "analyze", text: t };
  const m2 = /\b(create|make|generate|build|write|prepare|export|convert|produce|draft)\b.{0,40}?\b(pdf|pptx?|powerpoint|slides?|deck|presentation|docx?|word|csv|xlsx|excel|spreadsheet)\b/.exec(low);
  if (m2) return { kind: FORMAT_WORDS[m2[2]], text: t };
  if (/\b(best|recommend|suggest|which)\b.{0,25}\b(design|theme|style|template|palette)\b/.test(low)) return { kind: "design", text: t };
  return { kind: "chat", text: t };
}

