import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import { isDownloading } from "./format";
import type { Asset, Job, Limits, ModelRow, Settings, SystemInfo } from "./types";

interface Toast { id: number; text: string; error: boolean }

interface AppCtx {
  system: SystemInfo | null; limits: Limits | null; settings: Settings | null; models: ModelRow[];
  assets: Asset[]; jobs: Job[]; ready: boolean; connectionLost: boolean;
  refreshAssets: () => Promise<void>; refreshModels: () => Promise<void>; refreshAll: () => Promise<void>;
  setSettings: (p: Partial<Settings>) => Promise<void>;
  toast: (text: string, error?: boolean) => void; toasts: Toast[];
  watchJob: (job: Job, onDone?: (job: Job) => void) => void;
  asset: (id: string) => Asset | undefined;
  needsSetup: boolean;
}

const Ctx = createContext<AppCtx | null>(null);
export const useApp = (): AppCtx => {
  const v = useContext(Ctx);
  if (!v) throw new Error("useApp outside provider");
  return v;
};

export function AppProvider({ children }: { children: ReactNode }) {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [settings, setSettingsState] = useState<Settings | null>(null);
  const [models, setModels] = useState<ModelRow[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [ready, setReady] = useState(false);
  const [lost, setLost] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const callbacks = useRef(new Map<string, (j: Job) => void>());
  const seen = useRef(new Set<string>());
  const nextId = useRef(1);

  const toast = useCallback((text: string, error = false) => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, text, error }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), error ? 8000 : 4000);
  }, []);

  const refreshAssets = useCallback(async () => { try { setAssets(await api.assets()); } catch { /* shown by connectionLost */ } }, []);
  const refreshModels = useCallback(async () => { try { setModels((await api.models()).items); } catch { /* ditto */ } }, []);
  const refreshAll = useCallback(async () => {
    const [s, l, st] = await Promise.all([api.system(), api.limits(), api.settings()]);
    setSystem(s); setLimits(l); setSettingsState(st);
    await Promise.all([refreshAssets(), refreshModels()]);
  }, [refreshAssets, refreshModels]);

  useEffect(() => { refreshAll().then(() => setReady(true)).catch(() => setLost(true)); }, [refreshAll]);

  const watchJob = useCallback((job: Job, onDone?: (j: Job) => void) => {
    setJobs((j) => [job, ...j.filter((x) => x.id !== job.id)]);
    if (onDone) callbacks.current.set(job.id, onDone);
  }, []);

  // One poll loop for everything that runs in the background: jobs, and downloads while any is active.
  const active = jobs.some((j) => j.status === "queued" || j.status === "running");
  const downloading = models.some((m) => isDownloading(m.download.status));
  useEffect(() => {
    if (!ready) return;
    let stop = false;
    const tick = async () => {
      try {
        const list = await api.jobs();
        if (stop) return;
        setLost(false);
        setJobs(list);
        for (const j of list) {
          if (j.status === "done" || j.status === "error" || j.status === "cancelled") {
            if (!seen.current.has(j.id)) {
              seen.current.add(j.id);
              if (j.status === "error") toast(j.error ?? "Something failed.", true);
              await refreshAssets();
              callbacks.current.get(j.id)?.(j);
              callbacks.current.delete(j.id);
            }
          }
        }
        if (downloading) await refreshModels();
      } catch {
        if (!stop) setLost(true);
      }
    };
    const handle = setInterval(tick, active || downloading ? 800 : 4000);
    return () => { stop = true; clearInterval(handle); };
  }, [ready, active, downloading, refreshAssets, refreshModels, toast]);

  // Jobs that finished before this window opened must not toast again.
  useEffect(() => { if (ready) api.jobs().then((l) => l.forEach((j) => { if (j.status !== "queued" && j.status !== "running") seen.current.add(j.id); })).catch(() => {}); }, [ready]);

  const setSettings = useCallback(async (p: Partial<Settings>) => {
    try {
      setSettingsState(await api.saveSettings(p));
      const [s, l] = await Promise.all([api.system(), api.limits()]);
      setSystem(s); setLimits(l);
    } catch (e) { toast((e as Error).message, true); }
  }, [toast]);

  const assetMap = useMemo(() => new Map(assets.map((a) => [a.id, a])), [assets]);
  const needsSetup = !!system && system.requires_models && !models.some((m) => m.kind === "model" && m.installed);

  const value: AppCtx = {
    system, limits, settings, models, assets, jobs, ready, connectionLost: lost,
    refreshAssets, refreshModels, refreshAll, setSettings, toast, toasts, watchJob,
    asset: (id) => assetMap.get(id), needsSetup,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
