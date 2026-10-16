import { useCallback, useRef, useState } from "react";

/** Undo/redo for one document. Rapid edits with the same key (slider drags, typing) collapse into one undo step. */
export function useHistory<T>(initial: T) {
  const [state, setState] = useState({ past: [] as T[], present: initial, future: [] as T[] });
  const last = useRef<{ key: string; at: number } | null>(null);

  const commit = useCallback((next: T | ((p: T) => T), key?: string) => {
    setState((s) => {
      const value = typeof next === "function" ? (next as (p: T) => T)(s.present) : next;
      if (value === s.present) return s;
      const now = Date.now();
      const merge = key && last.current && last.current.key === key && now - last.current.at < 700;
      last.current = key ? { key, at: now } : null;
      return { past: merge ? s.past : [...s.past.slice(-99), s.present], present: value, future: [] };
    });
  }, []);
  const undo = useCallback(() => { last.current = null; setState((s) => (s.past.length ? { past: s.past.slice(0, -1), present: s.past[s.past.length - 1], future: [s.present, ...s.future] } : s)); }, []);
  const redo = useCallback(() => { last.current = null; setState((s) => (s.future.length ? { past: [...s.past, s.present], present: s.future[0], future: s.future.slice(1) } : s)); }, []);
  const reset = useCallback((v: T) => { last.current = null; setState({ past: [], present: v, future: [] }); }, []);
  /** Jump to any earlier or later step: 0 is the oldest. */
  const jump = useCallback((i: number) => { last.current = null; setState((s) => { const all = [...s.past, s.present, ...s.future]; if (i < 0 || i >= all.length || i === s.past.length) return s; return { past: all.slice(0, i), present: all[i], future: all.slice(i + 1) }; }); }, []);
  return { value: state.present, steps: [...state.past, state.present, ...state.future], at: state.past.length, jump, commit, undo, redo, reset, canUndo: state.past.length > 0, canRedo: state.future.length > 0 };
}
