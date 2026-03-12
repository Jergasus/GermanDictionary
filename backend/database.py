"""
Database connection module for MongoDB Atlas.
Uses motor (async MongoDB driver) for non-blocking operations.
"""

import os
import certifi
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = "german_dictionary"

client: AsyncIOMotorClient | None = None
db = None


async def connect_db():
    """Connect to MongoDB Atlas and create indexes."""
    global client, db
    if not MONGODB_URI:
        raise ValueError("MONGODB_URI environment variable is not set. Copy .env.example to .env and fill in your connection string.")

    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]

    # Create indexes for fast search
    words = db.words
    await words.create_index([("lemma", "text"), ("normalized_form", "text")], name="text_search")
    await words.create_index([("language", 1), ("normalized_form", 1)], name="lang_normalized")
    await words.create_index([("alternative_forms.form_text", 1)], name="alt_forms")
    await words.create_index([("language", 1), ("lemma", 1)], name="lang_lemma")

    # Verify connection
    await client.admin.command("ping")
    print(f"✅ Connected to MongoDB Atlas — database: {DB_NAME}")


async def close_db():
    """Close the MongoDB connection."""
    global client
    if client:
        client.close()
        print("🔌 MongoDB connection closed")


def get_db():
    """Get the database instance."""
    if db is None:
        raise RuntimeError("Database not connected. Call connect_db() first.")
    return db
