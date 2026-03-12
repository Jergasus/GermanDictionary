"use client";

import { SearchResult } from "@/lib/api";
import WordCard from "./WordCard";

interface SearchResultsProps {
  results: SearchResult[];
  suggestions: string[];
  query: string;
  isLoading: boolean;
  onSuggestionClick: (suggestion: string) => void;
}

export default function SearchResults({
  results,
  suggestions,
  query,
  isLoading,
  onSuggestionClick,
}: SearchResultsProps) {
  // Loading state
  if (isLoading) {
    return (
      <div className="w-full max-w-2xl mx-auto mt-8">
        <div className="flex flex-col gap-4">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="bg-white/[0.04] border border-white/5 rounded-2xl p-5 animate-pulse"
            >
              <div className="h-6 bg-white/10 rounded-lg w-1/3 mb-3" />
              <div className="h-4 bg-white/5 rounded-lg w-1/2 mb-2" />
              <div className="h-4 bg-white/5 rounded-lg w-2/3" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // No query — show nothing
  if (!query) return null;

  // No results
  if (results.length === 0 && query) {
    return (
      <div className="w-full max-w-2xl mx-auto mt-8 text-center">
        <div className="bg-white/[0.04] border border-white/10 rounded-2xl p-8">
          <div className="text-3xl mb-3">🔍</div>
          <p className="text-white/60 text-lg">
            No se encontraron resultados para{" "}
            <span className="font-semibold text-white/80">
              &ldquo;{query}&rdquo;
            </span>
          </p>

          {suggestions.length > 0 && (
            <div className="mt-5">
              <p className="text-white/40 text-sm mb-3">¿Quisiste decir...?</p>
              <div className="flex flex-wrap gap-2 justify-center">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => onSuggestionClick(s)}
                    className="px-4 py-2.5 min-h-[44px] rounded-xl text-sm font-medium
                               bg-amber-500/10 border border-amber-400/20 text-amber-200
                               hover:bg-amber-500/20 hover:border-amber-400/30
                               active:bg-amber-500/30 transition-all duration-200"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Results list
  return (
    <div className="w-full max-w-2xl mx-auto mt-6">
      <p className="text-white/30 text-sm mb-4">
        {results.length} {results.length === 1 ? "resultado" : "resultados"}
      </p>

      <div className="flex flex-col gap-3">
        {results.map((result) => (
          <WordCard key={result.id} result={result} />
        ))}
      </div>

      {/* Suggestions even with some results */}
      {suggestions.length > 0 && results.length < 3 && (
        <div className="mt-6 text-center">
          <p className="text-white/30 text-sm mb-3">Búsquedas relacionadas</p>
          <div className="flex flex-wrap gap-2 justify-center">
            {suggestions.map((s) => (
              <button
                key={s}
                onClick={() => onSuggestionClick(s)}
                className="px-4 py-2 min-h-[44px] rounded-lg text-sm
                           bg-white/5 border border-white/10 text-white/50
                           hover:bg-white/10 hover:text-white/70
                           active:bg-white/15 transition-all duration-200"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
