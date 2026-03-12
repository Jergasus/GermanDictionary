"""
Enrich dictionary entries with Wiktionary (Kaikki) and Tatoeba data.

Usage:
    python enrich_data.py --wiktionary          # Enrich DE entries with German Kaikki
    python enrich_data.py --wiktionary-es       # Enrich ES entries with Spanish Kaikki
    python enrich_data.py --tatoeba             # Add Tatoeba German-Spanish example sentences
    python enrich_data.py --all                 # Run all enrichments

Data files expected in backend/data/:
    - kaikki-german.jsonl.gz          (from kaikki.org)
    - kaikki-spanish.jsonl.gz         (from kaikki.org)
    - deu-spa_links.tsv.bz2          (from Tatoeba)
    - deu_sentences_detailed.tsv.bz2  (from Tatoeba)
    - spa_sentences_detailed.tsv.bz2  (from Tatoeba)
"""

import asyncio
import argparse
import bz2
import gzip
import json
import os
import re
import sys
from collections import defaultdict

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = "german_dictionary"
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# ─────────────────────────────────────────────────────────────────
# Wiktionary / Kaikki enrichment
# ─────────────────────────────────────────────────────────────────

# Map Kaikki POS to our schema POS
KAIKKI_POS_MAP = {
    "noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb",
    "prep": "preposition", "conj": "conjunction", "pron": "pronoun",
    "intj": "interjection", "num": "numeral", "particle": "particle",
    "det": "determiner", "name": "proper_noun", "phrase": "phrase",
    "suffix": "suffix", "prefix": "prefix", "article": "article",
}

# Tags we want for key verb forms (German)
DE_VERB_FORM_TAGS = {
    "1st_person_singular": ({"first-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "2nd_person_singular": ({"second-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "3rd_person_singular": ({"third-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "past_tense": ({"first-person", "singular", "indicative", "preterite"}, {"multiword-construction"}),
    "past_participle": ({"past", "participle"}, {"multiword-construction"}),
    "present_participle": ({"present", "participle"}, {"multiword-construction"}),
    "imperative": ({"imperative", "singular", "second-person"}, {"multiword-construction"}),
}

# Tags for Spanish verb conjugation forms
ES_VERB_FORM_TAGS = {
    "1st_person_singular": ({"first-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "2nd_person_singular": ({"second-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "3rd_person_singular": ({"third-person", "singular", "indicative", "present"}, {"multiword-construction"}),
    "past_tense": ({"first-person", "singular", "indicative", "preterite"}, {"multiword-construction"}),
    "past_participle": ({"past", "participle", "masculine", "singular"}, {"multiword-construction"}),
    "gerund": ({"gerund"}, {"multiword-construction"}),
    "imperative": ({"imperative", "singular", "second-person"}, {"multiword-construction"}),
}


def extract_wiktionary_data(entry: dict, lang: str = "de") -> dict | None:
    """Extract enrichment data from a single Kaikki JSONL entry."""
    word = entry.get("word", "").strip()
    pos = entry.get("pos", "")
    if not word or not pos:
        return None

    our_pos = KAIKKI_POS_MAP.get(pos, pos)
    forms = entry.get("forms", [])
    sounds = entry.get("sounds", [])

    # Extract pronunciation — prefer phonemic (/.../) over phonetic ([...])
    pronunciation = None
    phonetic_fallback = None
    for s in sounds:
        ipa = s.get("ipa", "")
        if not ipa:
            continue
        if ipa.startswith("/"):
            pronunciation = ipa
            break
        elif ipa.startswith("[") and not phonetic_fallback:
            phonetic_fallback = ipa
    if not pronunciation:
        pronunciation = phonetic_fallback

    # Extract gender for nouns
    gender = None
    if our_pos == "noun":
        # Gender is often in the first few tags of forms or in head_templates
        for ht in entry.get("head_templates", []):
            expansion = ht.get("expansion", "").lower()
            if " m " in expansion or expansion.startswith("m ") or "{m}" in ht.get("args", {}).get("2", ""):
                gender = "m"
            elif " f " in expansion or expansion.startswith("f ") or "{f}" in ht.get("args", {}).get("2", ""):
                gender = "f"
            elif " n " in expansion or expansion.startswith("n ") or "{n}" in ht.get("args", {}).get("2", ""):
                gender = "n"
            # Check args for gender
            for k, v in ht.get("args", {}).items():
                if v in ("m", "masculine"):
                    gender = "m"
                elif v in ("f", "feminine"):
                    gender = "f"
                elif v in ("n", "neuter"):
                    gender = "n"

        # Also try from tags on forms
        if not gender:
            for f in forms:
                tags = set(f.get("tags", []))
                if "table-tags" in tags:
                    if "masculine" in tags:
                        gender = "m"
                    elif "feminine" in tags:
                        gender = "f"
                    elif "neuter" in tags:
                        gender = "n"
                    break

    # Extract plural form for nouns
    plural_form = None
    if our_pos == "noun":
        # Priority 1: plural + nominative
        for f in forms:
            tags = set(f.get("tags", []))
            if "plural" in tags and "nominative" in tags and "multiword-construction" not in tags:
                form_text = f.get("form", "").strip()
                if form_text and form_text != word:
                    plural_form = form_text
                    break
        # Priority 2: just "plural" tag (common in Spanish Kaikki)
        if not plural_form:
            for f in forms:
                tags = set(f.get("tags", []))
                if "plural" in tags and "multiword-construction" not in tags and "table-tags" not in tags and "inflection-template" not in tags:
                    form_text = f.get("form", "").strip()
                    if form_text and form_text != word:
                        plural_form = form_text
                        break

    # Extract alternative forms (key inflections)
    alternative_forms = []
    seen_forms = set()

    if our_pos == "noun":
        # For nouns: plural, genitive
        for f in forms:
            tags = set(f.get("tags", []))
            form_text = f.get("form", "").strip()
            if not form_text or form_text == word or form_text in seen_forms:
                continue
            if "table-tags" in tags or "inflection-template" in tags:
                continue

            if "plural" in tags and "nominative" in tags:
                if form_text not in seen_forms:
                    alternative_forms.append({"form_text": form_text, "form_type": "plural"})
                    seen_forms.add(form_text)
            elif "genitive" in tags and "singular" in tags:
                if form_text not in seen_forms:
                    alternative_forms.append({"form_text": form_text, "form_type": "genitive"})
                    seen_forms.add(form_text)

    elif our_pos == "verb":
        # For verbs: key conjugation forms (language-specific tags)
        verb_tags = ES_VERB_FORM_TAGS if lang == "es" else DE_VERB_FORM_TAGS
        for form_type, (required_tags, excluded_tags) in verb_tags.items():
            for f in forms:
                tags = set(f.get("tags", []))
                form_text = f.get("form", "").strip()
                if not form_text or form_text == word or form_text in seen_forms:
                    continue
                if required_tags.issubset(tags) and not excluded_tags.intersection(tags):
                    alternative_forms.append({"form_text": form_text, "form_type": form_type})
                    seen_forms.add(form_text)
                    break

    elif our_pos == "adjective":
        # For adjectives: comparative, superlative, feminine, plural
        for f in forms:
            tags = set(f.get("tags", []))
            form_text = f.get("form", "").strip()
            if not form_text or form_text == word or form_text in seen_forms:
                continue
            if "table-tags" in tags or "inflection-template" in tags:
                continue
            if "comparative" in tags and len(tags) <= 2:
                alternative_forms.append({"form_text": form_text, "form_type": "comparative"})
                seen_forms.add(form_text)
            elif "superlative" in tags and len(tags) <= 2:
                alternative_forms.append({"form_text": form_text, "form_type": "superlative"})
                seen_forms.add(form_text)
            elif lang == "es" and "feminine" in tags and "singular" in tags and len(tags) <= 3:
                alternative_forms.append({"form_text": form_text, "form_type": "feminine"})
                seen_forms.add(form_text)
            elif lang == "es" and "plural" in tags and "masculine" in tags and len(tags) <= 3:
                alternative_forms.append({"form_text": form_text, "form_type": "plural"})
                seen_forms.add(form_text)

    return {
        "word": word,
        "pos": our_pos,
        "pronunciation": pronunciation,
        "gender": gender,
        "plural_form": plural_form,
        "alternative_forms": alternative_forms,
    }


def load_wiktionary_index(filename: str, lang_code: str = "de") -> dict[str, list[dict]]:
    """Load Kaikki JSONL and build word→[enrichment_data] index."""
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        print(f"❌ Kaikki file not found: {filepath}")
        sys.exit(1)

    print(f"📖 Loading Wiktionary data from {filepath}...")
    index: dict[str, list[dict]] = defaultdict(list)
    count = 0
    skipped = 0

    with gzip.open(filepath, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue

            # Only entries for the target language
            if entry.get("lang_code") != lang_code:
                skipped += 1
                continue

            data = extract_wiktionary_data(entry, lang=lang_code)
            if data:
                index[data["word"].lower()].append(data)
                count += 1

            if count % 50000 == 0 and count > 0:
                print(f"   ⏳ Loaded {count} entries...")

    print(f"   ✅ Loaded {count} Wiktionary entries ({skipped} skipped)")
    return dict(index)


async def enrich_with_wiktionary(lang: str = "de"):
    """Enrich MongoDB entries with Wiktionary data (forms, pronunciation, gender, plural)."""
    if lang == "de":
        wikt_index = load_wiktionary_index("kaikki-german.jsonl.gz", "de")
    else:
        wikt_index = load_wiktionary_index("kaikki-spanish.jsonl.gz", "es")

    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    words_col = db.words

    total = await words_col.count_documents({"language": lang})
    print(f"🔄 Enriching {total} {lang.upper()} entries with Wiktionary data...")

    updated = 0
    no_match = 0
    batched = 0
    batch = []
    BATCH_SIZE = 500

    cursor = words_col.find({"language": lang})

    async for doc in cursor:
        lemma = doc.get("lemma", "")
        lemma_lower = lemma.lower()
        pos = doc.get("part_of_speech", "unknown")

        wikt_entries = wikt_index.get(lemma_lower, [])
        if not wikt_entries:
            no_match += 1
            continue

        # Find best match by POS
        best = None
        for w in wikt_entries:
            if w["pos"] == pos:
                best = w
                break
        if not best:
            best = wikt_entries[0]

        # Build update
        update_fields = {}

        if best.get("pronunciation") and not doc.get("pronunciation"):
            update_fields["pronunciation"] = best["pronunciation"]
        if best.get("gender") and not doc.get("gender"):
            update_fields["gender"] = best["gender"]
        if best.get("plural_form") and not doc.get("plural_form"):
            update_fields["plural_form"] = best["plural_form"]

        existing_forms = {f["form_text"].lower() for f in doc.get("alternative_forms", [])}
        new_forms = [af for af in best.get("alternative_forms", []) if af["form_text"].lower() not in existing_forms]

        if update_fields or new_forms:
            update_op = {}
            if update_fields:
                update_op["$set"] = update_fields
            if new_forms:
                update_op["$push"] = {"alternative_forms": {"$each": new_forms}}

            batch.append(UpdateOne({"_id": doc["_id"]}, update_op))
            batched += 1

            if len(batch) >= BATCH_SIZE:
                result = await words_col.bulk_write(batch, ordered=False)
                updated += result.modified_count
                print(f"   ⏳ Batched {batched}, modified {updated}...")
                batch = []

    # Flush remaining batch
    if batch:
        result = await words_col.bulk_write(batch, ordered=False)
        updated += result.modified_count

    print(f"✅ Wiktionary enrichment ({lang.upper()}): {batched} batched, {updated} modified, {no_match} no match")
    client.close()


def infer_spanish_gender(word: str) -> str | None:
    """Infer Spanish noun gender from word ending heuristics.
    
    For multi-word phrases, extract the core noun and infer from that.
    """
    w = word.lower().strip()
    if not w:
        return None

    # For multi-word phrases, try to find the core noun
    # Patterns: "X de Y" → X is the noun, "X Y" → first word often the noun
    if " " in w:
        # Split on " de ", " del ", " a ", " con ", " en ", " para ", " por ", " sin "
        core = w.split(" de ")[0].split(" del ")[0].split(" a ")[0].strip()
        # Take the last word of the core (handles "casa blanca" → "casa")
        parts = core.split()
        if parts:
            w = parts[0]  # First word is usually the noun
        else:
            return None

    # Feminine patterns (high confidence)
    if w.endswith(("ción", "sión", "ión")):
        return "f"
    if w.endswith(("dad", "tad", "tud")):
        return "f"
    if w.endswith(("umbre", "eza", "anza", "encia", "ancia", "icie")):
        return "f"
    if w.endswith("itis"):  # medical: bronquitis, etc.
        return "f"

    # Greek-origin -ma words → masculine
    GREEK_MA = {"problema", "sistema", "tema", "programa", "diagrama", "panorama",
                "drama", "trauma", "plasma", "fantasma", "idioma", "diploma",
                "clima", "enigma", "dogma", "dilema", "paradigma", "esquema",
                "lema", "poema", "teorema", "axioma", "carisma", "magma",
                "asma", "prisma", "estigma", "aroma", "coma", "soma", "karma",
                "piama", "pijama", "crucigrama", "telegrama", "anagrama"}
    if w in GREEK_MA:
        return "m"

    # Masculine patterns (high confidence)
    if w.endswith(("aje", "mente")):
        return "m"
    if w.endswith("or") and not w.endswith(("sor", "flor", "labor", "color")):
        return "m"

    # General -o/-a rules (most reliable)
    if w.endswith("o"):
        return "m"
    if w.endswith("a"):
        return "f"

    # Masculine by ending (less certain but common)
    if w.endswith(("ón", "án")):
        return "m"

    return None


def infer_spanish_plural(word: str) -> str | None:
    """Infer Spanish plural from word ending rules."""
    w = word.strip()
    if not w or " " in w:
        return None

    lower = w.lower()
    if lower.endswith("z"):
        return w[:-1] + ("ces" if w[-1] == "z" else "Ces")
    if lower.endswith(("a", "e", "i", "o", "u", "á", "é", "ó")):
        return w + "s"
    if lower.endswith(("í", "ú")):
        return w + "es"
    if lower.endswith("s") or lower.endswith("x"):
        return None  # No change or ambiguous
    if lower[-1].isalpha():
        return w + "es"
    return None


async def infer_missing_fields():
    """Infer gender and plural for Spanish nouns not matched by Wiktionary.
    Also infer plural for German nouns with simple suffix rules."""
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    col = db.words

    # --- Spanish gender + plural inference ---
    missing_gender = col.find({
        "language": "es",
        "part_of_speech": "noun",
        "gender": None,
    })
    
    batch = []
    inferred_gender = 0
    inferred_plural = 0
    BATCH_SIZE = 500

    async for doc in missing_gender:
        lemma = doc["lemma"]
        update = {}
        
        g = infer_spanish_gender(lemma)
        if g:
            update["gender"] = g
            inferred_gender += 1
        
        if not doc.get("plural_form") and " " not in lemma:
            p = infer_spanish_plural(lemma)
            if p:
                update["plural_form"] = p
                inferred_plural += 1
        
        if update:
            batch.append(UpdateOne({"_id": doc["_id"]}, {"$set": update}))
            if len(batch) >= BATCH_SIZE:
                await col.bulk_write(batch, ordered=False)
                batch = []

    # Also infer plural for ES nouns that have gender but no plural
    missing_plural = col.find({
        "language": "es",
        "part_of_speech": "noun",
        "gender": {"$ne": None},
        "plural_form": None,
    })
    async for doc in missing_plural:
        lemma = doc["lemma"]
        if " " in lemma:
            continue
        p = infer_spanish_plural(lemma)
        if p:
            batch.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"plural_form": p}}))
            inferred_plural += 1
            if len(batch) >= BATCH_SIZE:
                await col.bulk_write(batch, ordered=False)
                batch = []

    if batch:
        await col.bulk_write(batch, ordered=False)
        batch = []
    
    print(f"✅ ES inference: {inferred_gender} genders, {inferred_plural} plurals inferred")
    client.close()


# ─────────────────────────────────────────────────────────────────
# Tatoeba example sentences
# ─────────────────────────────────────────────────────────────────

def load_tatoeba_sentences(filepath: str) -> dict[int, str]:
    """Load sentences from a Tatoeba bz2 file. Returns {sentence_id: text}."""
    sentences = {}
    with bz2.open(filepath, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 3:
                try:
                    sid = int(parts[0])
                    text = parts[2]
                    sentences[sid] = text
                except (ValueError, IndexError):
                    continue
    return sentences


def load_tatoeba_links(filepath: str) -> list[tuple[int, int]]:
    """Load deu-spa links. Returns [(deu_id, spa_id), ...]."""
    links = []
    with bz2.open(filepath, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split("\t")
            if len(parts) >= 2:
                try:
                    links.append((int(parts[0]), int(parts[1])))
                except ValueError:
                    continue
    return links


def tokenize_german(sentence: str) -> set[str]:
    """Simple tokenizer: extract lowercase words from a German sentence."""
    words = re.findall(r"[a-zA-ZäöüÄÖÜß]+", sentence)
    return {w.lower() for w in words}


async def enrich_with_tatoeba(max_examples_per_word: int = 3):
    """Add Tatoeba German-Spanish example sentence pairs to dictionary entries.
    
    Matches by lemma AND alternative_forms for better coverage.
    """

    links_file = os.path.join(DATA_DIR, "deu-spa_links.tsv.bz2")
    deu_file = os.path.join(DATA_DIR, "deu_sentences_detailed.tsv.bz2")
    spa_file = os.path.join(DATA_DIR, "spa_sentences_detailed.tsv.bz2")

    for f in [links_file, deu_file, spa_file]:
        if not os.path.exists(f):
            print(f"❌ Missing Tatoeba file: {f}")
            sys.exit(1)

    print("📖 Loading Tatoeba data...")

    print("   Loading German sentences...")
    deu_sentences = load_tatoeba_sentences(deu_file)
    print(f"   ✅ {len(deu_sentences)} German sentences")

    print("   Loading Spanish sentences...")
    spa_sentences = load_tatoeba_sentences(spa_file)
    print(f"   ✅ {len(spa_sentences)} Spanish sentences")

    print("   Loading deu-spa links...")
    links = load_tatoeba_links(links_file)
    print(f"   ✅ {len(links)} links")

    print("   Building sentence pairs...")
    pairs = []
    for deu_id, spa_id in links:
        deu_text = deu_sentences.get(deu_id)
        spa_text = spa_sentences.get(spa_id)
        if deu_text and spa_text:
            pairs.append((deu_text, spa_text))

    print(f"   ✅ {len(pairs)} valid German-Spanish sentence pairs")

    # Build word→examples indexes for both languages
    print("   Indexing sentences by word token...")
    max_per_token = max_examples_per_word * 5
    deu_word_examples: dict[str, list[tuple[str, str]]] = defaultdict(list)
    spa_word_examples: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for deu_text, spa_text in pairs:
        for token in tokenize_german(deu_text):
            if len(deu_word_examples[token]) < max_per_token:
                deu_word_examples[token].append((deu_text, spa_text))

        spa_tokens = {w.lower() for w in re.findall(r"[a-zA-ZáéíóúñÁÉÍÓÚÑüÜ]+", spa_text)}
        for token in spa_tokens:
            if len(spa_word_examples[token]) < max_per_token:
                spa_word_examples[token].append((spa_text, deu_text))

    print(f"   ✅ Indexed {len(deu_word_examples)} DE tokens, {len(spa_word_examples)} ES tokens")

    # --- Enrich DE entries ---
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    words_col = db.words

    total_de = await words_col.count_documents({"language": "de"})
    print(f"🔄 Adding Tatoeba examples to {total_de} German entries...")

    updated_de = 0
    batched_de = 0
    skipped_full = 0
    batch = []
    BATCH_SIZE = 500

    cursor = words_col.find({"language": "de"})
    async for doc in cursor:
        existing_examples = doc.get("examples", [])
        existing_count = len(existing_examples)
        if existing_count >= max_examples_per_word:
            skipped_full += 1
            continue

        # Search tokens: lemma + all alternative_forms
        lemma = doc.get("lemma", "").lower()
        search_tokens = {lemma}
        for af in doc.get("alternative_forms", []):
            ft = af.get("form_text", "").lower()
            if ft:
                search_tokens.add(ft)

        # Collect candidate examples
        candidates = []
        seen_deu = {e.get("source_sentence", "") for e in existing_examples}
        for token in search_tokens:
            for pair in deu_word_examples.get(token, []):
                if pair[0] not in seen_deu and len(pair[0]) <= 200:
                    candidates.append(pair)
                    seen_deu.add(pair[0])
                if len(candidates) >= max_examples_per_word * 3:
                    break
            if len(candidates) >= max_examples_per_word * 3:
                break

        if not candidates:
            continue

        candidates.sort(key=lambda x: len(x[0]))
        needed = max_examples_per_word - existing_count
        new_examples = [
            {"source_sentence": d, "translated_sentence": s}
            for d, s in candidates[:needed]
        ]

        if new_examples:
            batch.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$push": {"examples": {"$each": new_examples}}}
            ))
            batched_de += 1
            if len(batch) >= BATCH_SIZE:
                result = await words_col.bulk_write(batch, ordered=False)
                updated_de += result.modified_count
                print(f"   ⏳ DE: batched {batched_de}, modified {updated_de}...")
                batch = []

    if batch:
        result = await words_col.bulk_write(batch, ordered=False)
        updated_de += result.modified_count
        batch = []

    print(f"   DE: {batched_de} batched, {updated_de} modified, {skipped_full} already full")

    # --- Enrich ES entries ---
    print("🔄 Adding Tatoeba examples to Spanish entries...")
    updated_es = 0
    batched_es = 0
    batch = []

    cursor = words_col.find({"language": "es"})
    async for doc in cursor:
        existing_examples = doc.get("examples", [])
        existing_count = len(existing_examples)
        if existing_count >= max_examples_per_word:
            continue

        lemma = doc.get("lemma", "").lower()
        search_tokens = {lemma}
        for af in doc.get("alternative_forms", []):
            ft = af.get("form_text", "").lower()
            if ft:
                search_tokens.add(ft)

        candidates = []
        seen_src = {e.get("source_sentence", "") for e in existing_examples}
        for token in search_tokens:
            for pair in spa_word_examples.get(token, []):
                if pair[0] not in seen_src and len(pair[0]) <= 200:
                    candidates.append(pair)
                    seen_src.add(pair[0])
                if len(candidates) >= max_examples_per_word * 3:
                    break
            if len(candidates) >= max_examples_per_word * 3:
                break

        if not candidates:
            continue

        candidates.sort(key=lambda x: len(x[0]))
        needed = max_examples_per_word - existing_count
        new_examples = [
            {"source_sentence": s, "translated_sentence": d}
            for s, d in candidates[:needed]
        ]

        if new_examples:
            batch.append(UpdateOne(
                {"_id": doc["_id"]},
                {"$push": {"examples": {"$each": new_examples}}}
            ))
            batched_es += 1
            if len(batch) >= BATCH_SIZE:
                result = await words_col.bulk_write(batch, ordered=False)
                updated_es += result.modified_count
                print(f"   ⏳ ES: batched {batched_es}, modified {updated_es}...")
                batch = []

    if batch:
        result = await words_col.bulk_write(batch, ordered=False)
        updated_es += result.modified_count

    print(f"   ES: {batched_es} batched, {updated_es} modified")
    print(f"✅ Tatoeba enrichment: {updated_de} DE + {updated_es} ES entries modified")
    client.close()


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Enrich dictionary data with Wiktionary & Tatoeba")
    parser.add_argument("--wiktionary", action="store_true", help="Enrich DE entries with German Kaikki")
    parser.add_argument("--wiktionary-es", action="store_true", help="Enrich ES entries with Spanish Kaikki")
    parser.add_argument("--tatoeba", action="store_true", help="Add Tatoeba German-Spanish example sentences")
    parser.add_argument("--infer", action="store_true", help="Infer missing ES gender/plural from word ending rules")
    parser.add_argument("--all", action="store_true", help="Run all enrichments")
    parser.add_argument("--max-examples", type=int, default=3, help="Max examples per word (default: 3)")
    args = parser.parse_args()

    if not MONGODB_URI:
        print("❌ MONGODB_URI not set. Copy .env.example to .env and fill in your connection string.")
        sys.exit(1)

    if not any([args.wiktionary, args.wiktionary_es, args.tatoeba, args.infer, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.wiktionary or args.all:
        await enrich_with_wiktionary("de")

    if args.wiktionary_es or args.all:
        await enrich_with_wiktionary("es")

    if args.infer or args.all:
        await infer_missing_fields()

    if args.tatoeba or args.all:
        await enrich_with_tatoeba(max_examples_per_word=args.max_examples)

    print("\n🎉 Enrichment complete!")


if __name__ == "__main__":
    asyncio.run(main())
