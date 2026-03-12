"""
German-Spanish Dictionary API
FastAPI application with CORS, search, and word lookup endpoints.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from database import connect_db, close_db
from search import search_words, get_suggestions, get_word_by_id
from models import SearchResponse, SuggestionResponse

import os
from dotenv import load_dotenv

load_dotenv()

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Build allowed origins list
_origins = [
    FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:3001",
]
# Allow all subdomains on Vercel for preview deploys
ALLOWED_ORIGINS = [o for o in _origins if o]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    await connect_db()
    yield
    await close_db()


app = FastAPI(
    title="German-Spanish Dictionary API",
    description="Fast, clean German↔Spanish dictionary API for language learners",
    version="1.0.0",
    lifespan=lifespan,
)


def _allow_origin(origin: str) -> bool:
    """Allow listed origins + any *.vercel.app subdomain."""
    if origin in ALLOWED_ORIGINS:
        return True
    if origin.endswith(".vercel.app") and origin.startswith("https://"):
        return True
    return False


# CORS — allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "german-spanish-dictionary"}


@app.get("/api/search", response_model=SearchResponse)
async def search(
    q: str = Query(..., min_length=1, max_length=100, description="Search query"),
    lang: str = Query("de", pattern="^(de|es)$", description="Source language: 'de' or 'es'"),
    limit: int = Query(20, ge=1, le=50, description="Max results"),
):
    """
    Search for words. Supports:
    - Exact match
    - Lemmatization (geht → gehen)
    - Umlaut normalization (schueler → schüler)
    - Fuzzy matching for typos
    """
    result = await search_words(q, lang, limit)
    return SearchResponse(**result)


@app.get("/api/word/{word_id}")
async def get_word(word_id: str):
    """Get full details for a specific word entry."""
    word = await get_word_by_id(word_id)
    if not word:
        raise HTTPException(status_code=404, detail="Word not found")
    return word


@app.get("/api/suggestions", response_model=SuggestionResponse)
async def suggestions(
    q: str = Query(..., min_length=1, max_length=100, description="Query prefix"),
    lang: str = Query("de", pattern="^(de|es)$", description="Language"),
):
    """Get autocomplete suggestions for a query prefix."""
    result = await get_suggestions(q, lang)
    return SuggestionResponse(query=q, suggestions=result)
