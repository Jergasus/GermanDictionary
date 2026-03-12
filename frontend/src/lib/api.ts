/**
 * API client for the German-Spanish Dictionary backend.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface Translation {
  text: string;
  target_language: string;
  sense_order: number;
}

export interface Example {
  source_sentence: string;
  translated_sentence: string;
}

export interface SearchResult {
  id: string;
  lemma: string;
  language: string;
  part_of_speech: string;
  gender: string | null;
  plural_form: string | null;
  pronunciation: string | null;
  translations: Translation[];
  examples: Example[];
  match_type: string;
}

export interface SearchResponse {
  query: string;
  language: string;
  results: SearchResult[];
  total: number;
  suggestions: string[];
}

export interface SuggestionResponse {
  query: string;
  suggestions: string[];
}

/**
 * Search for words in the dictionary.
 */
export async function searchWords(
  query: string,
  lang: string = "de",
  limit: number = 20,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, lang, limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/search?${params}`);
  if (!res.ok) throw new Error(`Search failed: ${res.statusText}`);
  return res.json();
}

/**
 * Get autocomplete suggestions.
 */
export async function getSuggestions(
  query: string,
  lang: string = "de",
): Promise<SuggestionResponse> {
  const params = new URLSearchParams({ q: query, lang });
  const res = await fetch(`${API_BASE}/api/suggestions?${params}`);
  if (!res.ok) throw new Error(`Suggestions failed: ${res.statusText}`);
  return res.json();
}

/**
 * Get full word details by ID.
 */
export async function getWord(id: string): Promise<SearchResult> {
  const res = await fetch(`${API_BASE}/api/word/${id}`);
  if (!res.ok) throw new Error(`Word fetch failed: ${res.statusText}`);
  return res.json();
}
