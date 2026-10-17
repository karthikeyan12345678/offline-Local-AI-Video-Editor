// Font files for the live preview. data/catalog.json says which file belongs to which font; it is read once before the app starts.
interface F { id: string; file: string; file_bold: string }
let table: Record<string, F> = {};
export async function loadFontTable(): Promise<void> {
  try { const c = (await (await fetch(new URL("data/catalog.json", document.baseURI).href)).json()) as { fonts: F[] }; table = Object.fromEntries(c.fonts.map((f) => [f.id, f])); } catch { /* the preview falls back to a system font */ }
}
export const webFontUrl = (id: string, bold: boolean): string => {
  const f = table[id];
  return f ? new URL("fonts/" + encodeURIComponent(bold ? f.file_bold : f.file), document.baseURI).href : "";
};
