"use client";

import { SearchResult } from "@/lib/api";

interface WordCardProps {
  result: SearchResult;
}

const GENDER_LABELS: Record<string, { label: string; color: string }> = {
  m: { label: "der", color: "text-blue-300 bg-blue-500/20 border-blue-400/30" },
  f: { label: "die", color: "text-pink-300 bg-pink-500/20 border-pink-400/30" },
  n: {
    label: "das",
    color: "text-emerald-300 bg-emerald-500/20 border-emerald-400/30",
  },
};

const POS_LABELS: Record<string, string> = {
  noun: "Sustantivo",
  verb: "Verbo",
  adjective: "Adjetivo",
  adverb: "Adverbio",
  preposition: "Preposición",
  conjunction: "Conjunción",
  pronoun: "Pronombre",
  proper_noun: "Nombre propio",
  interjection: "Interjección",
  phrase: "Frase",
  prefix: "Prefijo",
  suffix: "Sufijo",
  article: "Artículo",
  determiner: "Determinante",
  numeral: "Numeral",
  contraction: "Contracción",
  symbol: "Símbolo",
  character: "Carácter",
  proverb: "Proverbio",
  prep_phrase: "Frase preposicional",
  unknown: "",
};

function speakWord(word: string, lang: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  const utterance = new SpeechSynthesisUtterance(word);
  utterance.lang = lang === "de" ? "de-DE" : "es-ES";
  utterance.rate = 0.9;
  window.speechSynthesis.speak(utterance);
}

export default function WordCard({ result }: WordCardProps) {
  const genderInfo = result.gender ? GENDER_LABELS[result.gender] : null;
  const posLabel = POS_LABELS[result.part_of_speech] || result.part_of_speech;

  return (
    <div
      className="group bg-white/[0.06] border border-white/10 rounded-2xl p-4 sm:p-5 
                 hover:bg-white/[0.1] hover:border-white/20 
                 transition-all duration-200"
    >
      {/* Header: word + gender + POS */}
      <div className="flex items-start justify-between gap-2 sm:gap-3">
        <div className="flex items-center gap-2 flex-wrap min-w-0">
          {/* Gender badge for nouns */}
          {genderInfo && (
            <span
              className={`text-xs font-bold px-2 py-0.5 rounded-md border shrink-0 ${genderInfo.color}`}
            >
              {genderInfo.label}
            </span>
          )}

          {/* Word */}
          <h3 className="text-lg sm:text-xl font-semibold text-white break-words">{result.lemma}</h3>

          {/* Plural form */}
          {result.plural_form && (
            <span className="text-white/40 text-sm">
              (Pl. {result.plural_form})
            </span>
          )}
        </div>

        {/* Pronunciation button */}
        <button
          onClick={() => speakWord(result.lemma, result.language)}
          className="shrink-0 p-2.5 sm:p-2 rounded-xl bg-white/5 border border-white/10
                     hover:bg-white/15 hover:border-white/25 
                     transition-all duration-200 active:scale-90"
          aria-label={`Pronunciar ${result.lemma}`}
          title="Pronunciar"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-5 w-5 text-white/50 group-hover:text-amber-300 transition-colors"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z"
            />
          </svg>
        </button>
      </div>

      {/* POS label */}
      {posLabel && (
        <span className="mt-0.5 text-xs text-white/30 font-medium tracking-wide uppercase block">
          {posLabel}
        </span>
      )}

      {/* Translations */}
      <div className="mt-3 flex flex-wrap gap-2">
        {result.translations.map((t, i) => (
          <span
            key={i}
            className="inline-flex items-center px-3 py-1.5 rounded-lg
                       bg-amber-500/10 border border-amber-400/20
                       text-amber-200 text-sm font-medium"
          >
            {t.text}
          </span>
        ))}
      </div>

      {/* Example sentence */}
      {result.examples.length > 0 && (
        <div className="mt-4 pl-3 border-l-2 border-white/10">
          <p className="text-white/60 text-sm italic">
            &ldquo;{result.examples[0].source_sentence}&rdquo;
          </p>
          <p className="text-white/40 text-xs mt-1">
            &ldquo;{result.examples[0].translated_sentence}&rdquo;
          </p>
        </div>
      )}

      {/* Match type badge */}
      {result.match_type !== "exact" && (
        <div className="mt-3">
          <span className="text-xs text-white/20 bg-white/5 px-2 py-0.5 rounded-full">
            {result.match_type === "lemma"
              ? "Forma base"
              : result.match_type === "fuzzy"
                ? "Coincidencia aproximada"
                : result.match_type === "prefix"
                  ? "Coincidencia parcial"
                  : result.match_type}
          </span>
        </div>
      )}
    </div>
  );
}
