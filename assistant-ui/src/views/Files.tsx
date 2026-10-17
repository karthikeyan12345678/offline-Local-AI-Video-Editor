import { IS_WEB } from "../lib/env";
import { useCallback, useEffect, useState } from "react";
import { api, fileUrl } from "../lib/api";
import type { FileRef } from "../lib/types";
import { Banner, Button, DownloadLink, errText, fmtBytes } from "../ui";

export default function Files() {
  const [files, setFiles] = useState<FileRef[]>([]);
  const [tab, setTab] = useState<"generated" | "upload">("generated");
  const [err, setErr] = useState("");
  const load = useCallback(() => { api.files(tab).then(setFiles).catch((e) => setErr(errText(e))); }, [tab]);
  useEffect(load, [load]);
  return (
    <div className="page">
      <header><h1>Files</h1><p className="muted">Everything the assistant made, and files you uploaded. They are stored on {IS_WEB ? "this browser" : "this PC"} only.</p></header>
      <div className="chips" role="tablist" aria-label="File lists">
        <button className="chip" role="tab" aria-selected={tab === "generated"} onClick={() => setTab("generated")}>Created</button>
        <button className="chip" role="tab" aria-selected={tab === "upload"} onClick={() => setTab("upload")}>Uploaded</button></div>
      {err && <Banner kind="error">{err}</Banner>}
      {files.length === 0 ? <p className="muted">Nothing here yet.</p> : (
        <div className="table-wrap"><table className="table"><thead><tr><th>Name</th><th>Type</th><th className="num">Size</th><th></th></tr></thead><tbody>
          {files.map((f) => (<tr key={f.id}><td className="truncate" style={{ maxWidth: 360 }}>{f.kind === "png" ? <a href={fileUrl(f.id, true)} target="_blank" rel="noreferrer">{f.name}</a> : f.name}</td><td>{f.kind.toUpperCase()}</td><td className="num">{fmtBytes(f.size)}</td>
            <td style={{ textAlign: "right" }}><DownloadLink file={f} /> <Button variant="ghost" size="sm" onClick={() => { void api.deleteFile(f.id).then(load).catch((e) => setErr(errText(e))); }}>Delete</Button></td></tr>))}
        </tbody></table></div>)}
    </div>
  );
}
