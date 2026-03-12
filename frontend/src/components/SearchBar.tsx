"use client";

import { useState, useRef, useEffect } from "react";

interface SearchBarProps {
  onSearch: (query: string, lang: string) => void;
  isLoading: boolean;
}

const EXAMPLE_SEARCHES = {
  de: ["Haus", "gehen", "Freund", "schön", "sprechen"],
  es: ["casa", "hablar", "amigo", "grande", "hacer"],
};

export default function SearchBar({ onSearch, isLoading }: SearchBarProps) {
  const [query, setQuery] = useState("");
  const [lang, setLang] = useState<"de" | "es">("de");
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
      onSearch("", lang);
      return;
    }

    debounceRef.current = setTimeout(() => {
      onSearch(query.trim(), lang);
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, lang]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggleLang = () => {
    const newLang = lang === "de" ? "es" : "de";
    setLang(newLang);
    setQuery("");
  };

  const handleExampleClick = (word: string) => {
    setQuery(word);
  };

  const langLabel = lang === "de" ? "DE → ES" : "ES → DE";
  const placeholderText =
    lang === "de"
      ? "Buscar una palabra en alemán..."
      : "Buscar una palabra en español...";

  return (
    <div className="w-full max-w-2xl mx-auto">
      {/* Language toggle */}
      <div className="flex items-center justify-center mb-4">
        <button
          onClick={toggleLang}
          className="flex items-center gap-2 px-5 py-2.5 rounded-full 
                     bg-white/10 border border-white/20 text-white font-medium
                     hover:bg-white/20 transition-all duration-200 active:scale-95
                     backdrop-blur-sm"
          id="language-toggle"
          aria-label={`Cambiar dirección de búsqueda. Actual: ${langLabel}`}
        >
          <span
            className={`text-sm font-bold ${lang === "de" ? "text-amber-300" : "text-sky-300"}`}
          >
            {lang === "de" ? "🇩🇪 Deutsch" : "🇪🇸 Español"}
          </span>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4 text-white/60"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"
            />
          </svg>
          <span
            className={`text-sm font-bold ${lang === "de" ? "text-sky-300" : "text-amber-300"}`}
          >
            {lang === "de" ? "🇪🇸 Español" : "🇩🇪 Deutsch"}
          </span>
        </button>
      </div>

      {/* Search input */}
      <div className="relative">
        <div className="absolute inset-y-0 left-0 flex items-center pl-4 pointer-events-none">
          {isLoading ? (
            <svg
              className="animate-spin h-5 w-5 text-amber-300/70"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
            >
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
          ) : (
            <svg
              className="h-5 w-5 text-white/40"
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
              />
            </svg>
          )}
        </div>
        <input
          ref={inputRef}
          id="search-input"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={placeholderText}
          className="w-full pl-12 pr-4 py-4 rounded-2xl
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
          {EXAMPLE_SEARCHES[lang].map((word) => (
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
