"""
Import new German lemmas from Kaikki/Wiktionary that don't exist in the DB yet.
Translates DE→ES using Google Translate (free via deep-translator).

Also generates reverse ES→DE entries for the new translations.

Usage:
    python import_kaikki.py                # Import + translate all new Kaikki lemmas
    python import_kaikki.py --dry-run      # Just count, don't import
    python import_kaikki.py --limit 1000   # Import first N new entries only
    python import_kaikki.py --skip-names   # Skip proper nouns (name POS)
"""

import asyncio
import argparse
import gzip
import json
import os
import re
import sys
import time
from collections import defaultdict

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from deep_translator import GoogleTranslator

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = "german_dictionary"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# POS mapping (same as enrich_data.py)
KAIKKI_POS_MAP = {
    "noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb",
    "prep": "preposition", "conj": "conjunction", "pron": "pronoun",
    "intj": "interjection", "num": "numeral", "particle": "particle",
    "det": "determiner", "name": "proper_noun", "phrase": "phrase",
    "suffix": "suffix", "prefix": "prefix", "article": "article",
}

VERB_FORM_TAGS = {
    "1st_person_singular": ({"first-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "2nd_person_singular": ({"second-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "3rd_person_singular": ({"third-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "past_tense": ({"first-person", "singular", "indicative", "preterite"}, {"multiword-construction"}),
    "past_participle": ({"past", "participle"}, {"multiword-construction"}),
}


def normalize_umlauts(text: str) -> str:
    umlaut_map = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"}
    for u, r in umlaut_map.items():
        text = text.replace(u, r)
    return text


def extract_entry_data(entry: dict) -> dict | None:
    """Extract a full entry doc from a Kaikki JSONL entry."""
    word = entry.get("word", "").strip()
    pos = entry.get("pos", "")
    if not word or not pos:
        return None

    our_pos = KAIKKI_POS_MAP.get(pos, pos)
    forms = entry.get("forms", [])
    sounds = entry.get("sounds", [])

    # Skip form-of entries
    for sense in entry.get("senses", []):
        if sense.get("form_of"):
            return None

    # Pronunciation
    pronunciation = None
    for s in sounds:
        if "ipa" in s:
            pronunciation = s["ipa"]
            break

    # Gender
    gender = None
    if our_pos == "noun":
        for ht in entry.get("head_templates", []):
            for k, v in ht.get("args", {}).items():
                if v in ("m", "masculine"):
                    gender = "m"
                elif v in ("f", "feminine"):
                    gender = "f"
                elif v in ("n", "neuter"):
                    gender = "n"
            if not gender:
                expansion = ht.get("expansion", "").lower()
                if " m " in expansion or expansion.startswith("m "):
                    gender = "m"
                elif " f " in expansion or expansion.startswith("f "):
                    gender = "f"
                elif " n " in expansion or expansion.startswith("n "):
                    gender = "n"

    # Plural form
    plural_form = None
    if our_pos == "noun":
        for f in forms:
            tags = set(f.get("tags", []))
            if "plural" in tags and "nominative" in tags and "multiword-construction" not in tags:
                ft = f.get("form", "").strip()
                if ft and ft != word:
                    plural_form = ft
                    break
        if not plural_form:
            for f in forms:
                tags = set(f.get("tags", []))
                if tags == {"plural"} or tags == {"plural", "nominative"}:
                    ft = f.get("form", "").strip()
                    if ft and ft != word:
                        plural_form = ft
                        break

    # Alternative forms
    alternative_forms = []
    seen = set()

    if our_pos == "noun":
        for f in forms:
            tags = set(f.get("tags", []))
            ft = f.get("form", "").strip()
            if not ft or ft == word or ft in seen or "table-tags" in tags or "inflection-template" in tags:
                continue
            if "plural" in tags and "nominative" in tags:
                alternative_forms.append({"form_text": ft, "form_type": "plural"})
                seen.add(ft)
            elif "genitive" in tags and "singular" in tags:
                alternative_forms.append({"form_text": ft, "form_type": "genitive"})
                seen.add(ft)

    elif our_pos == "verb":
        for form_type, (required, excluded) in VERB_FORM_TAGS.items():
            for f in forms:
                tags = set(f.get("tags", []))
                ft = f.get("form", "").strip()
                if not ft or ft == word or ft in seen:
                    continue
                if required.issubset(tags) and not excluded.intersection(tags):
                    alternative_forms.append({"form_text": ft, "form_type": form_type})
                    seen.add(ft)
                    break

    elif our_pos == "adjective":
        for f in forms:
            tags = set(f.get("tags", []))
            ft = f.get("form", "").strip()
            if not ft or ft == word or ft in seen or "table-tags" in tags:
                continue
            if "comparative" in tags and len(tags) == 1:
                alternative_forms.append({"form_text": ft, "form_type": "comparative"})
                seen.add(ft)
            elif "superlative" in tags and len(tags) == 1:
                alternative_forms.append({"form_text": ft, "form_type": "superlative"})
                seen.add(ft)

    # Extract English glosses for context
    glosses = []
    for sense in entry.get("senses", []):
        for g in sense.get("glosses", []):
            if g and len(g) < 200:
                glosses.append(g)
                break
        if len(glosses) >= 3:
            break

    return {
        "word": word,
        "pos": our_pos,
        "pronunciation": pronunciation,
        "gender": gender,
        "plural_form": plural_form,
        "alternative_forms": alternative_forms,
        "glosses_en": glosses,
    }


def bulk_translate(words: list[str], source: str = "de", target: str = "es") -> list[str]:
    """Translate a list of words using newline-joined bulk Google Translate.

    Splits into chunks that fit the 5000-char API limit.
    Returns translations in the same order. On failure, returns empty strings.
    """
    translator = GoogleTranslator(source=source, target=target)
    results = [""] * len(words)
    MAX_CHARS = 4500  # leave margin

    # Build chunks
    chunks = []
    chunk_indices = []
    current_chunk = []
    current_indices = []
    current_len = 0

    for i, w in enumerate(words):
        word_len = len(w) + 1  # +1 for newline
        if current_len + word_len > MAX_CHARS and current_chunk:
            chunks.append(current_chunk)
            chunk_indices.append(current_indices)
            current_chunk = []
            current_indices = []
            current_len = 0
        current_chunk.append(w)
        current_indices.append(i)
        current_len += word_len

    if current_chunk:
        chunks.append(current_chunk)
        chunk_indices.append(current_indices)

    for ci, (chunk, indices) in enumerate(zip(chunks, chunk_indices)):
        joined = "\n".join(chunk)
        retries = 0
        while retries < 3:
            try:
                translated = translator.translate(joined)
                parts = translated.split("\n")
                # If line count doesn't match, fall back to individual
                if len(parts) == len(chunk):
                    for idx, trans in zip(indices, parts):
                        results[idx] = trans.strip()
                else:
                    # Mismatch — try one-by-one for this chunk
                    for idx, word in zip(indices, chunk):
                        try:
                            results[idx] = translator.translate(word).strip()
                        except Exception:
                            results[idx] = ""
                        time.sleep(0.1)
                break
            except Exception as e:
                retries += 1
                if retries >= 3:
                    print(f"   ⚠️  Translation failed for chunk {ci}: {e}")
                time.sleep(2 * retries)

    return results


async def import_kaikki_lemmas(dry_run: bool = False, limit: int = 0, skip_names: bool = False):
    """Import Kaikki German lemmas not already in DB, with Google Translate translations."""

    kaikki_file = os.path.join(DATA_DIR, "kaikki-german.jsonl.gz")
    if not os.path.exists(kaikki_file):
        print(f"❌ Missing: {kaikki_file}")
        sys.exit(1)

    # Load existing DE lemmas from DB
    print("📊 Loading existing entries from database...")
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    words_col = db.words

    existing_de = set()
    cursor = words_col.find({"language": "de"}, {"lemma": 1})
    async for doc in cursor:
        existing_de.add(doc["lemma"].lower())

    existing_es = set()
    cursor = words_col.find({"language": "es"}, {"lemma": 1})
    async for doc in cursor:
        existing_es.add(doc["lemma"].lower())

    print(f"   Existing: {len(existing_de)} DE, {len(existing_es)} ES")

    # Parse Kaikki for new lemmas
    print("📖 Scanning Kaikki for new German lemmas...")
    new_entries = {}  # (word_lower, pos) -> entry_data
    total_scanned = 0

    with gzip.open(kaikki_file, "rt", encoding="utf-8") as f:
        for line in f:
            entry = json.loads(line.strip())
            if entry.get("lang_code") != "de":
                continue
            total_scanned += 1

            data = extract_entry_data(entry)
            if not data:
                continue

            word = data["word"]
            pos = data["pos"]

            if skip_names and pos == "proper_noun":
                continue

            # Skip if already in DB
            if word.lower() in existing_de:
                continue

            key = (word.lower(), pos)
            if key not in new_entries:
                new_entries[key] = data

            if limit and len(new_entries) >= limit:
                break

    print(f"   Scanned {total_scanned} Kaikki entries")
    print(f"   Found {len(new_entries)} new lemmas to import")

    if dry_run:
        # Show POS distribution
        from collections import Counter
        pos_dist = Counter(v["pos"] for v in new_entries.values())
        print("\n   POS distribution of new entries:")
        for pos, count in pos_dist.most_common():
            print(f"     {pos:20s} {count:>6}")
        client.close()
        return

    if not new_entries:
        print("Nothing to import.")
        client.close()
        return

    # Prepare entries list
    entries_list = list(new_entries.values())
    words_to_translate = [e["word"] for e in entries_list]

    # Translate DE → ES in bulk
    print(f"🌐 Translating {len(words_to_translate)} words (DE→ES)...")
    t0 = time.time()
    translations_es = bulk_translate(words_to_translate, source="de", target="es")
    dt = time.time() - t0
    translated_count = sum(1 for t in translations_es if t)
    print(f"   ✅ {translated_count}/{len(words_to_translate)} translated in {dt:.1f}s")

    # Build MongoDB documents
    print("📝 Building documents...")
    de_docs = []
    es_docs = []

    for entry, trans_es in zip(entries_list, translations_es):
        word = entry["word"]
        trans_text = trans_es if trans_es and trans_es.lower() != word.lower() else ""

        translations = []
        if trans_text:
            translations.append({
                "text": trans_text,
                "target_language": "es",
                "sense_order": 1,
            })

        de_doc = {
            "lemma": word,
            "language": "de",
            "part_of_speech": entry["pos"],
            "gender": entry["gender"],
            "plural_form": entry["plural_form"],
            "pronunciation": entry["pronunciation"],
            "normalized_form": normalize_umlauts(word.lower()),
            "translations": translations,
            "examples": [],
            "alternative_forms": entry["alternative_forms"],
        }
        de_docs.append(de_doc)

        # Generate reverse ES→DE entry if we have a translation
        if trans_text and trans_text.lower() not in existing_es:
            existing_es.add(trans_text.lower())
            es_doc = {
                "lemma": trans_text,
                "language": "es",
                "part_of_speech": entry["pos"],
                "gender": None,
                "plural_form": None,
                "pronunciation": None,
                "normalized_form": normalize_umlauts(trans_text.lower()),
                "translations": [{"text": word, "target_language": "de", "sense_order": 1}],
                "examples": [],
                "alternative_forms": [],
            }
            es_docs.append(es_doc)

    # Insert DE entries
    print(f"💾 Inserting {len(de_docs)} DE entries...")
    batch_size = 1000
    total_de = 0
    for i in range(0, len(de_docs), batch_size):
        batch = de_docs[i:i + batch_size]
        result = await words_col.insert_many(batch)
        total_de += len(result.inserted_ids)
        if total_de % 5000 < batch_size:
            print(f"   ⏳ DE: {total_de}/{len(de_docs)}")

    print(f"   ✅ Inserted {total_de} DE entries")

    # Insert ES entries
    if es_docs:
        print(f"💾 Inserting {len(es_docs)} reverse ES entries...")
        total_es = 0
        for i in range(0, len(es_docs), batch_size):
            batch = es_docs[i:i + batch_size]
            result = await words_col.insert_many(batch)
            total_es += len(result.inserted_ids)
            if total_es % 5000 < batch_size:
                print(f"   ⏳ ES: {total_es}/{len(es_docs)}")
        print(f"   ✅ Inserted {total_es} ES entries")

    # Summary
    total_now = await words_col.count_documents({})
    de_now = await words_col.count_documents({"language": "de"})
    es_now = await words_col.count_documents({"language": "es"})
    print(f"\n🎉 Import complete!")
    print(f"   Database now has {total_now} entries (DE: {de_now}, ES: {es_now})")

    client.close()


async def main():
    parser = argparse.ArgumentParser(description="Import Kaikki German lemmas with translations")
    parser.add_argument("--dry-run", action="store_true", help="Count new entries without importing")
    parser.add_argument("--limit", type=int, default=0, help="Max entries to import (0 = all)")
    parser.add_argument("--skip-names", action="store_true", help="Skip proper nouns")
    args = parser.parse_args()

    if not MONGODB_URI:
        print("❌ MONGODB_URI not set")
        sys.exit(1)

    await import_kaikki_lemmas(
        dry_run=args.dry_run,
        limit=args.limit,
        skip_names=args.skip_names,
    )


if __name__ == "__main__":
    asyncio.run(main())
