"""
Deduplicate dictionary entries: merge entries with the same (lemma, language, POS)
into one, keeping the richest data. Also deduplicates translations within entries.

Usage:
    python dedup_entries.py              # Run deduplication
    python dedup_entries.py --dry-run    # Just count, don't modify
"""

import asyncio
import argparse
import os
import sys
from collections import defaultdict

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = "german_dictionary"


def merge_entries(docs: list[dict]) -> tuple[dict, list]:
    """Merge multiple docs for the same lemma into one, keeping richest data.
    
    Returns (merged_doc_to_keep, ids_to_delete).
    """
    # Sort: prefer entries with more translations, then more examples, then more alt_forms
    def richness(doc):
        return (
            len(doc.get("translations", [])),
            len(doc.get("examples", [])),
            len(doc.get("alternative_forms", [])),
            1 if doc.get("pronunciation") else 0,
            1 if doc.get("gender") else 0,
            1 if doc.get("plural_form") else 0,
        )

    docs.sort(key=richness, reverse=True)
    best = docs[0]
    others = docs[1:]

    # Merge data from others into best
    # Translations: collect unique by text (case-insensitive)
    seen_trans = {t["text"].lower() for t in best.get("translations", [])}
    merged_translations = list(best.get("translations", []))
    for doc in others:
        for t in doc.get("translations", []):
            if t["text"].lower() not in seen_trans:
                seen_trans.add(t["text"].lower())
                t["sense_order"] = len(merged_translations) + 1
                merged_translations.append(t)

    # Examples: collect unique by source_sentence
    seen_examples = {e["source_sentence"] for e in best.get("examples", [])}
    merged_examples = list(best.get("examples", []))
    for doc in others:
        for e in doc.get("examples", []):
            if e["source_sentence"] not in seen_examples:
                seen_examples.add(e["source_sentence"])
                merged_examples.append(e)

    # Alternative forms: collect unique by form_text
    seen_forms = {f["form_text"].lower() for f in best.get("alternative_forms", [])}
    merged_forms = list(best.get("alternative_forms", []))
    for doc in others:
        for f in doc.get("alternative_forms", []):
            if f["form_text"].lower() not in seen_forms:
                seen_forms.add(f["form_text"].lower())
                merged_forms.append(f)

    # Fill in missing scalar fields from others
    for field in ["pronunciation", "gender", "plural_form"]:
        if not best.get(field):
            for doc in others:
                if doc.get(field):
                    best[field] = doc[field]
                    break

    best["translations"] = merged_translations
    best["examples"] = merged_examples
    best["alternative_forms"] = merged_forms

    ids_to_delete = [doc["_id"] for doc in others]
    return best, ids_to_delete


def dedup_translations(translations: list[dict]) -> list[dict]:
    """Remove duplicate translations (same text, case-insensitive)."""
    seen = set()
    result = []
    for t in translations:
        key = t["text"].lower()
        if key not in seen:
            seen.add(key)
            t["sense_order"] = len(result) + 1
            result.append(t)
    return result


async def run_dedup(dry_run: bool = False):
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    col = db.words

    total_before = await col.count_documents({})
    print(f"📊 Database has {total_before} entries")

    total_merged = 0
    total_deleted = 0
    total_trans_deduped = 0

    for lang in ["de", "es"]:
        print(f"\n🔄 Deduplicating {lang.upper()} entries...")

        # Find duplicate lemmas
        pipeline = [
            {"$match": {"language": lang}},
            {"$group": {"_id": "$lemma", "count": {"$sum": 1}, "ids": {"$push": "$_id"}}},
            {"$match": {"count": {"$gt": 1}}},
        ]

        dup_groups = []
        async for group in col.aggregate(pipeline):
            dup_groups.append(group)

        print(f"   Found {len(dup_groups)} lemmas with duplicates")

        # Merge duplicates — fetch all duplicate docs in one query
        all_dup_ids = []
        for group in dup_groups:
            all_dup_ids.extend(group["ids"])

        print(f"   Fetching {len(all_dup_ids)} docs...")
        docs_by_id = {}
        cursor = col.find({"_id": {"$in": all_dup_ids}})
        async for doc in cursor:
            docs_by_id[doc["_id"]] = doc

        ids_to_delete = []
        updates = []

        for group in dup_groups:
            docs = [docs_by_id[did] for did in group["ids"] if did in docs_by_id]
            if len(docs) < 2:
                continue

            merged, delete_ids = merge_entries(docs)
            ids_to_delete.extend(delete_ids)
            merged["translations"] = dedup_translations(merged["translations"])

            updates.append((merged["_id"], {
                "$set": {
                    "translations": merged["translations"],
                    "examples": merged["examples"],
                    "alternative_forms": merged["alternative_forms"],
                    "pronunciation": merged.get("pronunciation"),
                    "gender": merged.get("gender"),
                    "plural_form": merged.get("plural_form"),
                }
            }))

        print(f"   Entries to merge: {len(updates)}")
        print(f"   Entries to delete: {len(ids_to_delete)}")

        if not dry_run and ids_to_delete:
            for doc_id, update in updates:
                await col.update_one({"_id": doc_id}, update)
            total_merged += len(updates)

            result = await col.delete_many({"_id": {"$in": ids_to_delete}})
            total_deleted += result.deleted_count
            print(f"   ✅ Merged {len(updates)}, deleted {result.deleted_count}")

        # Dedup translations within remaining entries (even non-duplicates)
        print(f"   Deduplicating translations within {lang.upper()} entries...")
        cursor = col.find({"language": lang})
        trans_updates = 0

        async for doc in cursor:
            translations = doc.get("translations", [])
            if len(translations) <= 1:
                continue

            deduped = dedup_translations(translations)
            if len(deduped) < len(translations):
                if not dry_run:
                    await col.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"translations": deduped}}
                    )
                trans_updates += 1

        total_trans_deduped += trans_updates
        print(f"   {'Would fix' if dry_run else 'Fixed'} {trans_updates} entries with repeated translations")

    if not dry_run:
        total_after = await col.count_documents({})
        de_after = await col.count_documents({"language": "de"})
        es_after = await col.count_documents({"language": "es"})
        print(f"\n🎉 Deduplication complete!")
        print(f"   Merged: {total_merged} entries")
        print(f"   Deleted: {total_deleted} duplicate entries")
        print(f"   Fixed translations: {total_trans_deduped} entries")
        print(f"   Before: {total_before} → After: {total_after}")
        print(f"   DE: {de_after}, ES: {es_after}")
    else:
        print(f"\n📋 Dry run summary:")
        print(f"   Would merge: {len([g for g in dup_groups])} groups")
        print(f"   Would fix translations: {total_trans_deduped} entries")

    client.close()


async def main():
    parser = argparse.ArgumentParser(description="Deduplicate dictionary entries")
    parser.add_argument("--dry-run", action="store_true", help="Count only, don't modify")
    args = parser.parse_args()

    if not MONGODB_URI:
        print("❌ MONGODB_URI not set")
        sys.exit(1)

    await run_dedup(dry_run=args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
