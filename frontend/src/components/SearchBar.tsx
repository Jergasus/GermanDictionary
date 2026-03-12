"use client";

import { useState, useRef, useEffect } from "react";

interface SearchBarProps {
  onSearch: (query: string) => void;
}

const EXAMPLE_SEARCHES = ["Haus", "gehen", "Freund", "schön", "sprechen"];

export default function SearchBar({ onSearch }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Debounced search
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (query.trim().length === 0) {
      onSearch("");
      return;
    }

    debounceRef.current = setTimeout(() => {
      onSearch(query.trim());
    }, 500);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleExampleClick = (word: string) => {
    setQuery(word);
  };

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* Search input */}
      <div className="relative">
        <input
          ref={inputRef}
          id="search-input"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar una palabra en alemán..."
          className="w-full pl-5 pr-12 py-4 rounded-2xl
                     bg-white/10 border border-white/20 
                     text-white text-lg placeholder-white/30
                     focus:outline-none focus:ring-2 focus:ring-amber-400/50 focus:border-amber-400/50
                     backdrop-blur-sm transition-all duration-200"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            className="absolute inset-y-0 right-0 flex items-center pr-4 text-white/40 hover:text-white/70 transition-colors"
            aria-label="Limpiar búsqueda"
          >
            <svg
              className="h-5 w-5"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M6 18L18 6M6 6l12 12"
              />
            </svg>
          </button>
        )}
      </div>

      {/* Example suggestions when empty */}
      {!query && (
        <div className="mt-4 flex flex-wrap gap-2 justify-center items-center">
          <span className="text-white/30 text-sm mr-1">Prueba:</span>
          {EXAMPLE_SEARCHES.map((word) => (
            <button
              key={word}
              onClick={() => handleExampleClick(word)}
              className="px-4 py-2 min-h-[44px] rounded-full text-sm
                         bg-white/5 border border-white/10 text-white/50
                         hover:bg-white/15 hover:text-white/80 hover:border-white/25
                         active:bg-white/20 transition-all duration-200"
            >
              {word}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
