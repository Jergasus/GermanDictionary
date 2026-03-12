"""
Pydantic models for API request/response schemas.
"""

from pydantic import BaseModel, Field
from typing import Optional


class Translation(BaseModel):
    text: str
    target_language: str
    sense_order: int = 1


class Example(BaseModel):
    source_sentence: str
    translated_sentence: str


class AlternativeForm(BaseModel):
    form_text: str
    form_type: str = "inflection"


class WordEntry(BaseModel):
    id: str = Field(alias="_id", default="")
    lemma: str
    language: str
    part_of_speech: str = "unknown"
    gender: Optional[str] = None
    plural_form: Optional[str] = None
    pronunciation: Optional[str] = None
    normalized_form: str = ""
    translations: list[Translation] = []
    examples: list[Example] = []
    alternative_forms: list[AlternativeForm] = []

    class Config:
        populate_by_name = True


class SearchResult(BaseModel):
    id: str
    lemma: str
    language: str
    part_of_speech: str
    gender: Optional[str] = None
    plural_form: Optional[str] = None
    pronunciation: Optional[str] = None
    translations: list[Translation] = []
    examples: list[Example] = []
    match_type: str = "exact"  # exact, lemma, fuzzy


class SearchResponse(BaseModel):
    query: str
    language: str
    results: list[SearchResult]
    total: int
    suggestions: list[str] = []


class SuggestionResponse(BaseModel):
    query: str
    suggestions: list[str]
