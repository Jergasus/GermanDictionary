"""
Search engine with lemmatization, umlaut normalization, and fuzzy matching.
"""

import re
import simplemma
from rapidfuzz import fuzz, process
from database import get_db
from models import SearchResult, Translation, Example

# Umlaut equivalences for normalization
UMLAUT_MAP = {
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
    "Ä": "Ae", "Ö": "Oe", "Ü": "Ue",
}

REVERSE_UMLAUT_MAP = {
    "ae": "ä", "oe": "ö", "ue": "ü", "ss": "ß",
}


def normalize_umlauts(text: str) -> str:
    """Convert umlauts to their ASCII equivalents."""
    result = text
    for umlaut, replacement in UMLAUT_MAP.items():
        result = result.replace(umlaut, replacement)
    return result


def expand_umlaut_query(query: str) -> list[str]:
    """
    Generate possible umlaut variants of a query.
    e.g., 'schueler' -> ['schueler', 'schüler']
    """
    variants = [query]
    for ascii_form, umlaut in REVERSE_UMLAUT_MAP.items():
        if ascii_form in query.lower():
            variants.append(query.lower().replace(ascii_form, umlaut))
    return list(set(variants))


def lemmatize(word: str, lang: str) -> list[str]:
    """
    Get possible lemmas for a word using simplemma.
    Returns a list of candidate lemmas.
    """
    lang_code = "de" if lang == "de" else "es"
    lemma = simplemma.lemmatize(word, lang=lang_code)
    results = [word.lower()]
    if lemma.lower() != word.lower():
        results.append(lemma.lower())
    return list(set(results))


def normalize_query(query: str) -> str:
    """Normalize a search query: lowercase + strip + umlaut normalization."""
    return normalize_umlauts(query.strip().lower())


async def search_words(query: str, lang: str = "de", limit: int = 20) -> dict:
    """
    Main search function. Tries in order:
    1. Exact match on lemma
    2. Match on alternative_forms
    3. Lemmatized search
    4. Fuzzy matching
    """
    db = get_db()
    words_col = db.words
    query_clean = query.strip().lower()
    normalized = normalize_query(query)

    # Get lemma candidates
    lemma_candidates = lemmatize(query_clean, lang)

    # Expand umlaut variants
    umlaut_variants = expand_umlaut_query(query_clean)
    all_candidates = list(set(lemma_candidates + umlaut_variants + [normalized]))

    results = []
    seen_ids = set()

    # 1. Exact match on lemma
    exact_query = {
        "language": lang,
        "$or": [
            {"lemma": {"$regex": f"^{re.escape(query_clean)}$", "$options": "i"}},
            {"normalized_form": {"$regex": f"^{re.escape(normalized)}$", "$options": "i"}},
        ]
    }
    async for doc in words_col.find(exact_query).limit(limit):
        doc_id = str(doc["_id"])
        if doc_id not in seen_ids:
            seen_ids.add(doc_id)
            results.append(_doc_to_result(doc, "exact"))

    # 2. Match on alternative_forms
    if len(results) < limit:
        alt_query = {
            "language": lang,
            "alternative_forms.form_text": {"$regex": f"^{re.escape(query_clean)}$", "$options": "i"}
        }
        async for doc in words_col.find(alt_query).limit(limit - len(results)):
            doc_id = str(doc["_id"])
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                results.append(_doc_to_result(doc, "lemma"))

    # 3. Lemmatized match
    if len(results) < limit:
        for candidate in all_candidates:
            if candidate == query_clean:
                continue
            lemma_query = {
                "language": lang,
                "$or": [
                    {"lemma": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}},
                    {"normalized_form": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}},
                    {"alternative_forms.form_text": {"$regex": f"^{re.escape(candidate)}$", "$options": "i"}},
                ]
            }
            async for doc in words_col.find(lemma_query).limit(limit - len(results)):
                doc_id = str(doc["_id"])
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    results.append(_doc_to_result(doc, "lemma"))

    # 4. Prefix match for partial input
    if len(results) < limit:
        prefix_query = {
            "language": lang,
            "lemma": {"$regex": f"^{re.escape(query_clean)}", "$options": "i"}
        }
        async for doc in words_col.find(prefix_query).limit(limit - len(results)):
            doc_id = str(doc["_id"])
            if doc_id not in seen_ids:
                seen_ids.add(doc_id)
                results.append(_doc_to_result(doc, "prefix"))

    # 5. Fuzzy matching if still few results
    suggestions = []
    if len(results) < 3:
        suggestions = await _fuzzy_suggestions(query_clean, lang, limit=5)

    return {
        "query": query,
        "language": lang,
        "results": results[:limit],
        "total": len(results),
        "suggestions": suggestions,
    }


async def get_suggestions(query: str, lang: str = "de", limit: int = 8) -> list[str]:
    """Get autocomplete suggestions based on prefix match."""
    db = get_db()
    words_col = db.words
    query_clean = query.strip().lower()

    if len(query_clean) < 1:
        return []

    pipeline = [
        {
            "$match": {
                "language": lang,
                "lemma": {"$regex": f"^{re.escape(query_clean)}", "$options": "i"}
            }
        },
        {"$group": {"_id": "$lemma"}},
        {"$sort": {"_id": 1}},
        {"$limit": limit},
    ]

    results = []
    async for doc in words_col.aggregate(pipeline):
        results.append(doc["_id"])

    return results


async def get_word_by_id(word_id: str) -> dict | None:
    """Get a full word entry by its ID."""
    from bson import ObjectId
    db = get_db()
    try:
        doc = await db.words.find_one({"_id": ObjectId(word_id)})
        if doc:
            doc["_id"] = str(doc["_id"])
            return doc
    except Exception:
        return None
    return None


async def _fuzzy_suggestions(query: str, lang: str, limit: int = 5) -> list[str]:
    """Get fuzzy match suggestions using rapidfuzz."""
    db = get_db()
    words_col = db.words

    # Get a sample of lemmas to compare against
    cursor = words_col.find(
        {"language": lang},
        {"lemma": 1, "_id": 0}
    ).limit(5000)

    lemmas = []
    async for doc in cursor:
        lemmas.append(doc["lemma"])

    if not lemmas:
        return []

    # Use rapidfuzz for fuzzy matching
    matches = process.extract(
        query,
        lemmas,
        scorer=fuzz.ratio,
        limit=limit,
        score_cutoff=60,
    )

    return [match[0] for match in matches]


def _doc_to_result(doc: dict, match_type: str) -> SearchResult:
    """Convert a MongoDB document to a SearchResult."""
    return SearchResult(
        id=str(doc["_id"]),
        lemma=doc.get("lemma", ""),
        language=doc.get("language", ""),
        part_of_speech=doc.get("part_of_speech", "unknown"),
        gender=doc.get("gender"),
        plural_form=doc.get("plural_form"),
        pronunciation=doc.get("pronunciation"),
        translations=[
            Translation(**t) for t in doc.get("translations", [])
        ],
        examples=[
            Example(**e) for e in doc.get("examples", [])
        ],
        match_type=match_type,
    )
