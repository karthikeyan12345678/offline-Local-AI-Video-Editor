export interface FileRef { id: string; name: string; kind: string; size: number; origin?: string; created?: number }

export interface ThemeInfo {
  id: string; name: string; category: string; description: string; dark: boolean;
  colors: Record<string, string>; score?: number; reasons?: string[]; text_contrast?: number;
}

export interface Issue { severity: "high" | "medium" | "low"; category: string; message: string; fix: string }
export interface AtsCategory { label: string; score: number; max: number; matched?: Keyword[]; missing?: Keyword[]; skills_found?: string[]; mode?: string; coverage?: number }
export interface Keyword { keyword: string; weight: number; is_skill: boolean; in_resume?: number }
export interface AtsResult {
  score: number; level: string; categories: Record<string, AtsCategory>; issues: Issue[]; words: number; file: string;
  has_job_description: boolean; disclaimer: string; before_score?: number | null;
}

export interface Segment { t: "equal" | "ins" | "del"; x: string }
export interface TextDiffItem { type: "same" | "changed" | "added" | "removed"; a?: string; b?: string; a_index?: number; b_index?: number; segments?: Segment[] }
export interface TableChange {
  type: "added_row" | "removed_row" | "changed_row"; key?: string; row?: Record<string, string>; cells?: { column: string; old: string; new: string }[];
}
export interface TableDiff {
  name_a: string; name_b: string; columns_added: string[]; columns_removed: string[]; rows_a: number; rows_b: number; matched_by: string; similarity: number;
  rows_added: number; rows_removed: number; rows_changed: number; cells_changed: number; rows_same: number; changes: TableChange[];
  numeric_shifts: { column: string; cells: number; total_change: number; average_change: number }[]; truncated: boolean;
}
export interface CompareResult {
  a: { name: string; kind: string }; b: { name: string; kind: string }; similarity: number; identical: boolean; headline: string; warnings: string[]; mode: string;
  words?: { a: number; b: number; difference: number };
  diff?: { stats: { added: number; removed: number; changed: number; same: number }; items: TextDiffItem[]; truncated: boolean };
  tables?: TableDiff[]; sheets_only_in_a?: string[]; sheets_only_in_b?: string[];
}

export interface Column {
  name: string; type: string; count: number; missing: number; missing_pct: number;
  min?: number | string; max?: number | string; mean?: number; median?: number; std?: number; outliers?: number;
  histogram?: { from: number; to: number; count: number }[]; top?: { value: string; count: number; pct: number }[];
  by_month?: { month: string; count: number }[]; unique?: number; span_days?: number;
}
export interface TableAnalysis {
  name: string; rows: number; columns: number; duplicates: number; profiles: Column[];
  correlations: { a: string; b: string; r: number; n: number }[]; insights: { kind: string; message: string }[];
  preview: { columns: string[]; rows: string[][] };
}
export interface AnalyticsResult {
  file: string; kind: string; headline: string; warnings: string[]; tables: TableAnalysis[];
  text?: { words: number; sentences: number; paragraphs: number; reading_minutes: number; readability: number; avg_sentence_words: number; top_words: { word: string; count: number }[]; numbers_mentioned: number };
}

export type Card =
  | { type: "file"; file: FileRef; note: string; warnings: string[]; theme: { id: string; name: string; colors: Record<string, string>; reasons: string[] } | null }
  | { type: "markdown"; text: string }
  | { type: "ats"; result: AtsResult }
  | { type: "compare"; result: CompareResult; report: FileRef }
  | { type: "analytics"; result: AnalyticsResult }
  | { type: "image"; file: FileRef; prompt: string; width: number; height: number; provider: string }
  | { type: "themes"; themes: ThemeInfo[]; request: string }
  | { type: "error"; message: string };

export interface Message { id: string; role: "user" | "assistant"; content: string; cards: Card[]; files: FileRef[]; created: number }
export interface Conversation { id: string; title: string; updated: number; created: number }

export interface ProviderPreset { name: string; style: string; base_url: string; needs_key: boolean; model: string; help: string }
export interface Info {
  version: string; formats: string[]; providers: Record<string, ProviderPreset>;
  image_providers: Record<string, { name: string; needs_key: boolean; base_url: string; model: string; help: string }>;
  local_image: { available: boolean; reason: string }; supported_uploads: string[]; themes: number;
}
export interface SettingsData {
  provider: string; default_theme: string; system_prompt: string;
  providers: Record<string, { base_url?: string; model?: string; api_key_hint?: string }>;
  image: Record<string, unknown> & { provider: string };
}
