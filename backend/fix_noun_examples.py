"""
One-time script: clean up noun entries in MongoDB that have
examples not mentioning any noun form of the word.
"""
import asyncio
import re
import os
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from dotenv import load_dotenv

load_dotenv()
MONGODB_URI = os.getenv("MONGODB_URI", "")


def noun_pattern(doc):
    forms = {doc.get("lemma", "").strip()}
    if doc.get("plural_form"):
        forms.add(doc["plural_form"].strip())
    for af in doc.get("alternative_forms", []):
        ft = (af.get("form_text") or "").strip()
        if ft:
            forms.add(ft)
    forms = {f for f in forms if f}
    if not forms:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(f) for f in forms) + r")\b")


async def main():
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client.german_dictionary

    total = await db.words.count_documents(
        {"language": "de", "part_of_speech": "noun", "examples.0": {"$exists": True}}
    )
    print(f"Noun entries with examples: {total}")

    bad_removed = 0
    entries_fixed = 0
    entries_cleared = 0
    bulk = []
    BATCH = 500

    cursor = db.words.find(
        {"language": "de", "part_of_speech": "noun", "examples.0": {"$exists": True}}
    )
    async for doc in cursor:
        pat = noun_pattern(doc)
        if pat is None:
            continue

        good = [e for e in doc["examples"] if pat.search(e.get("source_sentence", ""))]
        removed = len(doc["examples"]) - len(good)
        if removed > 0:
            bad_removed += removed
            bulk.append(UpdateOne({"_id": doc["_id"]}, {"$set": {"examples": good}}))
            if good:
                entries_fixed += 1
            else:
                entries_cleared += 1

        if len(bulk) >= BATCH:
            await db.words.bulk_write(bulk, ordered=False)
            print(f"  ...batch written ({bad_removed} bad removed so far)")
            bulk = []

    if bulk:
        await db.words.bulk_write(bulk, ordered=False)

    print(f"\nDone.")
    print(f"  Bad examples removed: {bad_removed}")
    print(f"  Entries with some good examples kept: {entries_fixed}")
    print(f"  Entries fully cleared (no valid example): {entries_cleared}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
