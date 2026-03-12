"use client";

import { useState, useCallback } from "react";
import SearchBar from "@/components/SearchBar";
import SearchResults from "@/components/SearchResults";
import { searchWords, SearchResult } from "@/lib/api";

export default function Home() {
  const [results, setResults] = useState<SearchResult[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSearch = useCallback(async (q: string, lang: string) => {
    setQuery(q);

    if (!q.trim()) {
      setResults([]);
      setSuggestions([]);
      return;
    }

    setIsLoading(true);
    try {
      const data = await searchWords(q, lang);
      setResults(data.results);
      setSuggestions(data.suggestions);
    } catch (err) {
      console.error("Search error:", err);
      setResults([]);
      setSuggestions([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const handleSuggestionClick = useCallback(
    (suggestion: string) => {
      handleSearch(suggestion, "de");
    },
    [handleSearch],
  );

  return (
    <main className="min-h-dvh bg-gradient-to-br from-slate-950 via-slate-900 to-slate-950">
      {/* Header */}
      <header className="pt-safe">
        <div className="pt-6 sm:pt-12 pb-4 sm:pb-6 px-4 text-center">
          <h1 className="text-3xl sm:text-4xl font-bold text-white tracking-tight">
            <span className="text-amber-300">Wörter</span>
            <span className="text-white/80">buch</span>
          </h1>
          <p className="mt-1.5 sm:mt-2 text-white/30 text-sm sm:text-base">
            Diccionario Alemán ↔ Español
          </p>
        </div>
      </header>

      {/* Search area */}
      <section className="px-4 pb-4 sticky top-0 z-10 bg-gradient-to-b from-slate-950 via-slate-950/95 to-transparent pt-3">
        <SearchBar onSearch={handleSearch} isLoading={isLoading} />
      </section>

      {/* Results */}
      <section className="px-4 pb-8">
        <SearchResults
          results={results}
          suggestions={suggestions}
          query={query}
          isLoading={isLoading}
          onSuggestionClick={handleSuggestionClick}
        />
      </section>
    </main>
  );
}
