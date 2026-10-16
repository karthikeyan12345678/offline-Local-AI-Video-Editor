/** Saves a file and always lets the person choose where it goes.
 *  In the desktop app a Save As window opens (the app asks every time). In a browser, the file picker is used when available. */
export async function saveAs(url: string, filename: string): Promise<void> {
  const desktop = /Electron\//.test(navigator.userAgent);
  const picker = (window as unknown as { showSaveFilePicker?: (o: unknown) => Promise<{ createWritable: () => Promise<{ write: (b: Blob) => Promise<void>; close: () => Promise<void> }> }> }).showSaveFilePicker;
  if (!desktop && picker) {
    try {
      const handle = await picker({ suggestedName: filename, types: [{ description: "Video", accept: { "video/mp4": [".mp4"] } }] });
      const res = await fetch(url);
      if (!res.ok) throw new Error("The file could not be read.");
      const w = await handle.createWritable();
      await w.write(await res.blob());
      await w.close();
      return;
    } catch (e) {
      if ((e as Error).name === "AbortError") return; // the person closed the window
      /* fall through to a normal download */
    }
  }
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.rel = "noopener";
  document.body.appendChild(a); a.click(); a.remove();
}
