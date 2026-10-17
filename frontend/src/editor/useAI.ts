import { useCallback } from "react";
import { api, type AIRequest } from "../lib/api";
import { useApp } from "../lib/store";
import type { Job } from "../lib/types";

/** Starts a background AI job and resolves with its result (rejects with the readable error). */
export function useAI() {
  const { watchJob, toast } = useApp();
  const wait = useCallback((job: Job) => new Promise<Record<string, any>>((resolve, reject) => { // eslint-disable-line @typescript-eslint/no-explicit-any
    watchJob(job, (j) => (j.status === "done" ? resolve(j.result ?? {}) : reject(new Error(j.status === "cancelled" ? "Cancelled." : j.error ?? "Failed."))));
  }), [watchJob]);

  const run = useCallback(async (what: Parameters<typeof api.ai>[0], b: AIRequest) => wait(await api.ai(what, b)), [wait]);
  const speak = useCallback(async (text: string, voice: string, rate: number, persona?: Parameters<typeof api.speak>[3]) => wait(await api.speak(text, voice, rate, persona)), [wait]);
  return { run, speak, wait, toast };
}
