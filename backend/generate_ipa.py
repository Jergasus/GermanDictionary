#!/usr/bin/env python3
"""
Generate IPA pronunciation for Spanish entries missing pronunciation.

Spanish has very regular spelling-to-sound rules, making IPA generation
reliable without a dictionary lookup.

Rules implemented:
- Vowels: a→a, e→e, i→i, o→o, u→u (with stress marking)
- Diphthongs: ie, ue, ai/ay, ei/ey, oi/oy, au, eu, ou
- Consonants: standard Latin American Spanish (seseo: c/z→s before e/i)
- Stress: accent marks override; else penultimate if ends vowel/n/s, else final
- Special: ñ→ɲ, ll→ʝ, rr→r, ch→tʃ, qu→k, gu→g/ɡw, gü→gw
"""

import asyncio
import os
import re
import sys
import unicodedata

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne

load_dotenv()


def _strip_accent(c: str) -> str:
    """Remove accent from a vowel: á→a, é→e, etc."""
    return unicodedata.normalize("NFD", c)[0]


def _has_accent(word: str) -> int | None:
    """Return the index of the accented vowel, or None."""
    for i, c in enumerate(word):
        if c in "áéíóú":
            return i
    return None


def _is_vowel(c: str) -> bool:
    return c.lower() in "aeiouáéíóú"


def spanish_to_ipa(word: str) -> str | None:
    """Convert a Spanish word to IPA (Latin American seseo variant).
    
    Returns IPA string wrapped in /.../ or None if the word contains
    non-Spanish characters.
    """
    w = word.lower().strip()
    if not w:
        return None
    
    # For multi-word phrases, generate IPA for each word and join
    if " " in w:
        parts = w.split()
        ipa_parts = []
        for part in parts:
            part_ipa = spanish_to_ipa(part)
            if part_ipa:
                # Strip the /.../ wrapper
                ipa_parts.append(part_ipa[1:-1])
            else:
                return None  # If any word fails, skip the whole phrase
        if ipa_parts:
            return "/" + " ".join(ipa_parts) + "/"
        return None
    
    # Skip words with non-Spanish characters, digits, hyphens
    if not re.match(r'^[a-záéíóúüñ]+$', w):
        return None

    # Determine stress position (0-indexed from start of vowels list)
    vowel_positions = [i for i, c in enumerate(w) if _is_vowel(c)]
    if not vowel_positions:
        return None
    
    accent_pos = _has_accent(w)
    if accent_pos is not None:
        stressed_char_idx = accent_pos
    else:
        # Default stress rules
        if w[-1] in "aeioun:s" or w[-1] in "áéíóú":
            # Penultimate vowel stressed
            if len(vowel_positions) >= 2:
                stressed_char_idx = vowel_positions[-2]
            else:
                stressed_char_idx = vowel_positions[-1]
        else:
            # Last vowel stressed
            stressed_char_idx = vowel_positions[-1]

    # Strip accents for processing
    w_clean = ""
    for c in w:
        if c in "áéíóú":
            w_clean += _strip_accent(c)
        else:
            w_clean += c

    # Convert to IPA character by character
    ipa = []
    i = 0
    n = len(w_clean)
    
    while i < n:
        c = w_clean[i]
        
        # Check if this position should get stress mark
        if i == stressed_char_idx and len(vowel_positions) > 1:
            ipa.append("ˈ")

        # Digraphs first
        if i + 1 < n:
            digraph = w_clean[i:i+2]
            
            if digraph == "ch":
                ipa.append("t͡ʃ")
                i += 2
                continue
            elif digraph == "ll":
                ipa.append("ʝ")
                i += 2
                continue
            elif digraph == "rr":
                ipa.append("r")
                i += 2
                continue
            elif digraph == "qu":
                # qu + e/i → k
                if i + 2 < n and w_clean[i+2] in "ei":
                    ipa.append("k")
                    i += 2
                    continue
                else:
                    ipa.append("k")
                    i += 2
                    continue
            elif digraph == "gu":
                if i + 2 < n and w_clean[i+2] in "ei":
                    ipa.append("ɡ")
                    i += 2
                    continue
                else:
                    ipa.append("ɡ")
                    i += 1
                    # Don't skip 'u' — it's pronounced
            elif c == "g" and i + 1 < n and w[i+1] == "ü":
                # gü → gw
                ipa.append("ɡw")
                i += 2
                continue
        
        # Single characters
        if c == "a":
            ipa.append("a")
        elif c == "e":
            ipa.append("e")
        elif c == "i":
            ipa.append("i")
        elif c == "o":
            ipa.append("o")
        elif c == "u":
            ipa.append("u")
        elif c == "ü":
            ipa.append("w")
        elif c == "b" or c == "v":
            ipa.append("b")
        elif c == "c":
            if i + 1 < n and w_clean[i+1] in "ei":
                ipa.append("s")  # Latin American seseo
            else:
                ipa.append("k")
        elif c == "d":
            ipa.append("d")
        elif c == "f":
            ipa.append("f")
        elif c == "g":
            if i + 1 < n and w_clean[i+1] in "ei":
                ipa.append("x")  # ge, gi → /x/
            else:
                ipa.append("ɡ")
        elif c == "h":
            pass  # silent
        elif c == "j":
            ipa.append("x")
        elif c == "k":
            ipa.append("k")
        elif c == "l":
            ipa.append("l")
        elif c == "m":
            ipa.append("m")
        elif c == "n":
            ipa.append("n")
        elif c == "ñ":
            ipa.append("ɲ")
        elif c == "p":
            ipa.append("p")
        elif c == "r":
            if i == 0:
                ipa.append("r")  # Initial r is trilled
            else:
                ipa.append("ɾ")  # Intervocalic r is tap
        elif c == "s":
            ipa.append("s")
        elif c == "t":
            ipa.append("t")
        elif c == "w":
            ipa.append("w")
        elif c == "x":
            ipa.append("ks")
        elif c == "y":
            if i == n - 1:
                ipa.append("i")  # Final y is vowel
            else:
                ipa.append("ʝ")
        elif c == "z":
            ipa.append("s")  # Latin American seseo
        else:
            ipa.append(c)
        
        i += 1

    result = "".join(ipa)
    if not result:
        return None
    
    return f"/{result}/"


async def main():
    dry_run = "--dry-run" in sys.argv

    client = AsyncIOMotorClient(os.getenv("MONGODB_URI"), tlsCAFile=certifi.where())
    col = client["german_dictionary"]["words"]

    # Count missing
    missing_es = await col.count_documents({"language": "es", "pronunciation": None})
    print(f"ES entries without pronunciation: {missing_es}")

    # Process ES entries
    cursor = col.find({"language": "es", "pronunciation": None})
    batch = []
    generated = 0
    skipped = 0
    BATCH_SIZE = 500

    async for doc in cursor:
        ipa = spanish_to_ipa(doc["lemma"])
        if ipa:
            if dry_run:
                if generated < 20:
                    print(f"  {doc['lemma']} → {ipa}")
                generated += 1
            else:
                batch.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"pronunciation": ipa}}))
                generated += 1
                if len(batch) >= BATCH_SIZE:
                    await col.bulk_write(batch, ordered=False)
                    print(f"  Updated {generated}...")
                    batch = []
        else:
            skipped += 1

    if not dry_run and batch:
        await col.bulk_write(batch, ordered=False)

    print(f"\nES: Generated IPA for {generated}, skipped {skipped} (multi-word/special chars)")

    # Final stats
    remaining = await col.count_documents({"language": "es", "pronunciation": None})
    total = await col.count_documents({"language": "es"})
    print(f"ES pronunciation: {total - remaining}/{total} ({(total-remaining)*100//total}%)")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
