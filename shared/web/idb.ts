// Tiny IndexedDB helper: files (blobs), asset records and projects live in the browser, nowhere else.
import { dbName } from "./account";

const NAME = dbName(); // each signed-in person has their own database
const STORES = ["blobs", "assets", "projects", "history", "meta"] as const;
type Store = (typeof STORES)[number];

let dbp: Promise<IDBDatabase> | null = null;
function open(): Promise<IDBDatabase> {
  if (!dbp) {
    dbp = new Promise((resolve, reject) => {
      const req = indexedDB.open(NAME, 2);
      req.onupgradeneeded = () => { for (const s of STORES) if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s); };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error ?? new Error("The browser storage could not be opened."));
    });
  }
  return dbp;
}

async function tx<T>(store: Store, mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise<T>((resolve, reject) => {
    const t = db.transaction(store, mode);
    const r = fn(t.objectStore(store));
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error ?? new Error("The browser storage failed."));
  });
}

export const idb = {
  get: <T>(store: Store, key: string) => tx<T | undefined>(store, "readonly", (s) => s.get(key) as IDBRequest<T | undefined>),
  put: (store: Store, key: string, value: unknown) => tx(store, "readwrite", (s) => s.put(value, key)).then(() => undefined),
  del: (store: Store, key: string) => tx(store, "readwrite", (s) => s.delete(key)).then(() => undefined),
  all: <T>(store: Store) => tx<T[]>(store, "readonly", (s) => s.getAll() as IDBRequest<T[]>),
};

/** Ask the browser to keep the data (so it is not cleared when the disk is low). Best effort. */
export async function persist(): Promise<void> {
  try { await navigator.storage?.persist?.(); } catch { /* not supported */ }
}
