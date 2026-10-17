import { useEffect, useRef, useState } from "react";
import { IS_WEB, fontFileUrl, fontSampleUrl } from "../lib/api";

const loaded = new Set<string>();

/** One font drawn in its own letters. On the website the font file is fetched only when the row scrolls into view. */
export default function FontSample({ id, label, text, bold, height }: { id: string; label: string; text: string; bold: boolean; height: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const [ready, setReady] = useState(() => loaded.has(`${id}:${bold}`));
  useEffect(() => {
    if (!IS_WEB || ready || !ref.current) return;
    const key = `${id}:${bold}`;
    const io = new IntersectionObserver((entries) => {
      if (!entries[0]?.isIntersecting) return;
      io.disconnect();
      const url = fontFileUrl(id, bold);
      if (!url) return;
      const face = new FontFace(`vkf-${id}-${bold ? "b" : "r"}`, `url("${url}")`);
      face.load().then((f) => { document.fonts.add(f); loaded.add(key); setReady(true); }).catch(() => undefined);
    });
    io.observe(ref.current);
    return () => io.disconnect();
  }, [id, bold, ready]);
  if (!IS_WEB) return <img loading="lazy" src={fontSampleUrl(id, text, bold, height)} alt={label} height={Math.round(height / 1.8)} />;
  return <span ref={ref} className="font-sample" aria-label={label} style={{ fontFamily: ready ? `"vkf-${id}-${bold ? "b" : "r"}", system-ui` : "system-ui", fontSize: Math.round(height / 2.2), opacity: ready ? 1 : 0.5 }}>{text}</span>;
}
