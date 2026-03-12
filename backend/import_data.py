"""
Dictionary data import script.
Imports data from FreeDict TEI/XML files into MongoDB.

Usage:
    python import_data.py                      # Import seed data (built-in starter dictionary)
    python import_data.py --freedict FILE      # Import from FreeDict TEI XML (deu→spa)
    python import_data.py --freedict-spa FILE  # Import from FreeDict TEI XML (spa→deu)
    python import_data.py --generate-reverse   # Generate ES→DE entries from DE→ES

For enrichment (Wiktionary forms/pronunciation + Tatoeba examples), see:
    python enrich_data.py --help
"""

import asyncio
import argparse
import xml.etree.ElementTree as ET
import csv
import os
import sys
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient
import simplemma
import certifi

load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "")
DB_NAME = "german_dictionary"


def normalize_umlauts(text: str) -> str:
    """Convert umlauts to ASCII equivalents for normalized_form."""
    umlaut_map = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue"}
    for u, r in umlaut_map.items():
        text = text.replace(u, r)
    return text


def generate_alternative_forms(lemma: str, lang: str) -> list[dict]:
    """Generate known alternative/inflected forms for a word using simplemma."""
    # simplemma is primarily a lemmatizer (form → lemma),
    # but we store common forms manually for high-value words
    forms = []
    normalized = normalize_umlauts(lemma.lower())
    if normalized != lemma.lower():
        forms.append({"form_text": normalized, "form_type": "normalized"})
    return forms


def detect_gender_and_pos(entry_text: str, lemma: str) -> tuple[str, str | None, str | None]:
    """Try to detect part of speech, gender, and plural from entry text."""
    text_lower = entry_text.lower()
    gender = None
    plural = None
    pos = "unknown"

    # Detect gender for nouns
    if any(article in text_lower for article in ["der ", "die ", "das "]):
        pos = "noun"
        if "der " in text_lower:
            gender = "m"
        elif "die " in text_lower:
            gender = "f"
        elif "das " in text_lower:
            gender = "n"

    # Detect verbs
    if lemma.endswith("en") or lemma.endswith("ern") or lemma.endswith("eln"):
        if pos == "unknown":
            pos = "verb"

    # Detect adjectives (rough heuristic)
    if any(marker in text_lower for marker in ["adj.", "adjective", "adjetivo"]):
        pos = "adjective"

    return pos, gender, plural


# ─────────────────────────────────────────────
# SEED DATA — Common German-Spanish word pairs
# ─────────────────────────────────────────────

SEED_DATA = [
    # ── Nouns ──
    {"lemma": "Haus", "language": "de", "part_of_speech": "noun", "gender": "n", "plural_form": "Häuser",
     "translations": [{"text": "casa", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Das Haus ist groß.", "translated_sentence": "La casa es grande."}],
     "alternative_forms": [{"form_text": "Hauses", "form_type": "genitive"}, {"form_text": "Häuser", "form_type": "plural"}]},

    {"lemma": "Buch", "language": "de", "part_of_speech": "noun", "gender": "n", "plural_form": "Bücher",
     "translations": [{"text": "libro", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich lese ein Buch.", "translated_sentence": "Leo un libro."}],
     "alternative_forms": [{"form_text": "Bücher", "form_type": "plural"}]},

    {"lemma": "Schule", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Schulen",
     "translations": [{"text": "escuela", "target_language": "es", "sense_order": 1}, {"text": "colegio", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Die Kinder gehen zur Schule.", "translated_sentence": "Los niños van a la escuela."}],
     "alternative_forms": [{"form_text": "Schulen", "form_type": "plural"}]},

    {"lemma": "Freund", "language": "de", "part_of_speech": "noun", "gender": "m", "plural_form": "Freunde",
     "translations": [{"text": "amigo", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Er ist mein bester Freund.", "translated_sentence": "Él es mi mejor amigo."}],
     "alternative_forms": [{"form_text": "Freunde", "form_type": "plural"}, {"form_text": "Freundin", "form_type": "feminine"}]},

    {"lemma": "Wasser", "language": "de", "part_of_speech": "noun", "gender": "n",
     "translations": [{"text": "agua", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich trinke Wasser.", "translated_sentence": "Bebo agua."}],
     "alternative_forms": []},

    {"lemma": "Stadt", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Städte",
     "translations": [{"text": "ciudad", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Berlin ist eine große Stadt.", "translated_sentence": "Berlín es una gran ciudad."}],
     "alternative_forms": [{"form_text": "Städte", "form_type": "plural"}]},

    {"lemma": "Arbeit", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Arbeiten",
     "translations": [{"text": "trabajo", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Die Arbeit ist interessant.", "translated_sentence": "El trabajo es interesante."}],
     "alternative_forms": [{"form_text": "Arbeiten", "form_type": "plural"}]},

    {"lemma": "Kind", "language": "de", "part_of_speech": "noun", "gender": "n", "plural_form": "Kinder",
     "translations": [{"text": "niño", "target_language": "es", "sense_order": 1}, {"text": "hijo", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Das Kind spielt im Garten.", "translated_sentence": "El niño juega en el jardín."}],
     "alternative_forms": [{"form_text": "Kinder", "form_type": "plural"}, {"form_text": "Kindes", "form_type": "genitive"}]},

    {"lemma": "Tag", "language": "de", "part_of_speech": "noun", "gender": "m", "plural_form": "Tage",
     "translations": [{"text": "día", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Heute ist ein schöner Tag.", "translated_sentence": "Hoy es un bonito día."}],
     "alternative_forms": [{"form_text": "Tage", "form_type": "plural"}, {"form_text": "Tages", "form_type": "genitive"}]},

    {"lemma": "Frau", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Frauen",
     "translations": [{"text": "mujer", "target_language": "es", "sense_order": 1}, {"text": "señora", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Die Frau liest ein Buch.", "translated_sentence": "La mujer lee un libro."}],
     "alternative_forms": [{"form_text": "Frauen", "form_type": "plural"}]},

    {"lemma": "Mann", "language": "de", "part_of_speech": "noun", "gender": "m", "plural_form": "Männer",
     "translations": [{"text": "hombre", "target_language": "es", "sense_order": 1}, {"text": "marido", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Der Mann arbeitet viel.", "translated_sentence": "El hombre trabaja mucho."}],
     "alternative_forms": [{"form_text": "Männer", "form_type": "plural"}]},

    {"lemma": "Zeit", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Zeiten",
     "translations": [{"text": "tiempo", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich habe keine Zeit.", "translated_sentence": "No tengo tiempo."}],
     "alternative_forms": [{"form_text": "Zeiten", "form_type": "plural"}]},

    {"lemma": "Jahr", "language": "de", "part_of_speech": "noun", "gender": "n", "plural_form": "Jahre",
     "translations": [{"text": "año", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Das Jahr hat zwölf Monate.", "translated_sentence": "El año tiene doce meses."}],
     "alternative_forms": [{"form_text": "Jahre", "form_type": "plural"}, {"form_text": "Jahren", "form_type": "dative_plural"}]},

    {"lemma": "Mensch", "language": "de", "part_of_speech": "noun", "gender": "m", "plural_form": "Menschen",
     "translations": [{"text": "persona", "target_language": "es", "sense_order": 1}, {"text": "ser humano", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Der Mensch braucht Wasser.", "translated_sentence": "El ser humano necesita agua."}],
     "alternative_forms": [{"form_text": "Menschen", "form_type": "plural"}]},

    {"lemma": "Hund", "language": "de", "part_of_speech": "noun", "gender": "m", "plural_form": "Hunde",
     "translations": [{"text": "perro", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Der Hund spielt im Park.", "translated_sentence": "El perro juega en el parque."}],
     "alternative_forms": [{"form_text": "Hunde", "form_type": "plural"}]},

    {"lemma": "Katze", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Katzen",
     "translations": [{"text": "gato", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Die Katze schläft auf dem Sofa.", "translated_sentence": "El gato duerme en el sofá."}],
     "alternative_forms": [{"form_text": "Katzen", "form_type": "plural"}]},

    {"lemma": "Essen", "language": "de", "part_of_speech": "noun", "gender": "n",
     "translations": [{"text": "comida", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Das Essen schmeckt gut.", "translated_sentence": "La comida sabe bien."}],
     "alternative_forms": []},

    {"lemma": "Sprache", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Sprachen",
     "translations": [{"text": "idioma", "target_language": "es", "sense_order": 1}, {"text": "lengua", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Deutsch ist eine schwierige Sprache.", "translated_sentence": "El alemán es un idioma difícil."}],
     "alternative_forms": [{"form_text": "Sprachen", "form_type": "plural"}]},

    {"lemma": "Land", "language": "de", "part_of_speech": "noun", "gender": "n", "plural_form": "Länder",
     "translations": [{"text": "país", "target_language": "es", "sense_order": 1}, {"text": "tierra", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Deutschland ist ein schönes Land.", "translated_sentence": "Alemania es un país bonito."}],
     "alternative_forms": [{"form_text": "Länder", "form_type": "plural"}]},

    {"lemma": "Straße", "language": "de", "part_of_speech": "noun", "gender": "f", "plural_form": "Straßen",
     "translations": [{"text": "calle", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Die Straße ist lang.", "translated_sentence": "La calle es larga."}],
     "alternative_forms": [{"form_text": "Straßen", "form_type": "plural"}, {"form_text": "Strasse", "form_type": "alternate_spelling"}]},

    # ── Verbs ──
    {"lemma": "gehen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "ir", "target_language": "es", "sense_order": 1}, {"text": "caminar", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Ich gehe zur Schule.", "translated_sentence": "Voy a la escuela."}],
     "alternative_forms": [
         {"form_text": "gehe", "form_type": "1st_person_singular"},
         {"form_text": "gehst", "form_type": "2nd_person_singular"},
         {"form_text": "geht", "form_type": "3rd_person_singular"},
         {"form_text": "ging", "form_type": "past_tense"},
         {"form_text": "gingen", "form_type": "past_tense_plural"},
         {"form_text": "gegangen", "form_type": "past_participle"},
     ]},

    {"lemma": "haben", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "tener", "target_language": "es", "sense_order": 1}, {"text": "haber", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Ich habe einen Hund.", "translated_sentence": "Tengo un perro."}],
     "alternative_forms": [
         {"form_text": "habe", "form_type": "1st_person_singular"},
         {"form_text": "hast", "form_type": "2nd_person_singular"},
         {"form_text": "hat", "form_type": "3rd_person_singular"},
         {"form_text": "hatte", "form_type": "past_tense"},
         {"form_text": "gehabt", "form_type": "past_participle"},
     ]},

    {"lemma": "sein", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "ser", "target_language": "es", "sense_order": 1}, {"text": "estar", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Ich bin Student.", "translated_sentence": "Soy estudiante."}],
     "alternative_forms": [
         {"form_text": "bin", "form_type": "1st_person_singular"},
         {"form_text": "bist", "form_type": "2nd_person_singular"},
         {"form_text": "ist", "form_type": "3rd_person_singular"},
         {"form_text": "sind", "form_type": "1st_person_plural"},
         {"form_text": "war", "form_type": "past_tense"},
         {"form_text": "gewesen", "form_type": "past_participle"},
     ]},

    {"lemma": "machen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "hacer", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Was machst du?", "translated_sentence": "¿Qué haces?"}],
     "alternative_forms": [
         {"form_text": "mache", "form_type": "1st_person_singular"},
         {"form_text": "machst", "form_type": "2nd_person_singular"},
         {"form_text": "macht", "form_type": "3rd_person_singular"},
         {"form_text": "machte", "form_type": "past_tense"},
         {"form_text": "gemacht", "form_type": "past_participle"},
     ]},

    {"lemma": "kommen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "venir", "target_language": "es", "sense_order": 1}, {"text": "llegar", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Woher kommst du?", "translated_sentence": "¿De dónde vienes?"}],
     "alternative_forms": [
         {"form_text": "komme", "form_type": "1st_person_singular"},
         {"form_text": "kommst", "form_type": "2nd_person_singular"},
         {"form_text": "kommt", "form_type": "3rd_person_singular"},
         {"form_text": "kam", "form_type": "past_tense"},
         {"form_text": "gekommen", "form_type": "past_participle"},
     ]},

    {"lemma": "sagen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "decir", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Was hast du gesagt?", "translated_sentence": "¿Qué has dicho?"}],
     "alternative_forms": [
         {"form_text": "sage", "form_type": "1st_person_singular"},
         {"form_text": "sagst", "form_type": "2nd_person_singular"},
         {"form_text": "sagt", "form_type": "3rd_person_singular"},
         {"form_text": "sagte", "form_type": "past_tense"},
         {"form_text": "gesagt", "form_type": "past_participle"},
     ]},

    {"lemma": "wissen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "saber", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich weiß es nicht.", "translated_sentence": "No lo sé."}],
     "alternative_forms": [
         {"form_text": "weiß", "form_type": "1st_person_singular"},
         {"form_text": "weißt", "form_type": "2nd_person_singular"},
         {"form_text": "wusste", "form_type": "past_tense"},
         {"form_text": "gewusst", "form_type": "past_participle"},
     ]},

    {"lemma": "können", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "poder", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Können Sie mir helfen?", "translated_sentence": "¿Puede ayudarme?"}],
     "alternative_forms": [
         {"form_text": "kann", "form_type": "1st_person_singular"},
         {"form_text": "kannst", "form_type": "2nd_person_singular"},
         {"form_text": "konnte", "form_type": "past_tense"},
         {"form_text": "gekonnt", "form_type": "past_participle"},
     ]},

    {"lemma": "sprechen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "hablar", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Sprechen Sie Deutsch?", "translated_sentence": "¿Habla usted alemán?"}],
     "alternative_forms": [
         {"form_text": "spreche", "form_type": "1st_person_singular"},
         {"form_text": "sprichst", "form_type": "2nd_person_singular"},
         {"form_text": "spricht", "form_type": "3rd_person_singular"},
         {"form_text": "sprach", "form_type": "past_tense"},
         {"form_text": "gesprochen", "form_type": "past_participle"},
     ]},

    {"lemma": "essen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "comer", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich esse gern Obst.", "translated_sentence": "Me gusta comer fruta."}],
     "alternative_forms": [
         {"form_text": "esse", "form_type": "1st_person_singular"},
         {"form_text": "isst", "form_type": "2nd_person_singular"},
         {"form_text": "aß", "form_type": "past_tense"},
         {"form_text": "gegessen", "form_type": "past_participle"},
     ]},

    {"lemma": "trinken", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "beber", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich trinke Kaffee.", "translated_sentence": "Bebo café."}],
     "alternative_forms": [
         {"form_text": "trinke", "form_type": "1st_person_singular"},
         {"form_text": "trinkst", "form_type": "2nd_person_singular"},
         {"form_text": "trinkt", "form_type": "3rd_person_singular"},
         {"form_text": "trank", "form_type": "past_tense"},
         {"form_text": "getrunken", "form_type": "past_participle"},
     ]},

    {"lemma": "lernen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "aprender", "target_language": "es", "sense_order": 1}, {"text": "estudiar", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Ich lerne Deutsch.", "translated_sentence": "Aprendo alemán."}],
     "alternative_forms": [
         {"form_text": "lerne", "form_type": "1st_person_singular"},
         {"form_text": "lernst", "form_type": "2nd_person_singular"},
         {"form_text": "lernt", "form_type": "3rd_person_singular"},
         {"form_text": "lernte", "form_type": "past_tense"},
         {"form_text": "gelernt", "form_type": "past_participle"},
     ]},

    {"lemma": "schreiben", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "escribir", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich schreibe einen Brief.", "translated_sentence": "Escribo una carta."}],
     "alternative_forms": [
         {"form_text": "schreibe", "form_type": "1st_person_singular"},
         {"form_text": "schreibst", "form_type": "2nd_person_singular"},
         {"form_text": "schrieb", "form_type": "past_tense"},
         {"form_text": "geschrieben", "form_type": "past_participle"},
     ]},

    {"lemma": "lesen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "leer", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich lese gern Bücher.", "translated_sentence": "Me gusta leer libros."}],
     "alternative_forms": [
         {"form_text": "lese", "form_type": "1st_person_singular"},
         {"form_text": "liest", "form_type": "2nd_person_singular"},
         {"form_text": "las", "form_type": "past_tense"},
         {"form_text": "gelesen", "form_type": "past_participle"},
     ]},

    {"lemma": "schlafen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "dormir", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich kann nicht schlafen.", "translated_sentence": "No puedo dormir."}],
     "alternative_forms": [
         {"form_text": "schlafe", "form_type": "1st_person_singular"},
         {"form_text": "schläfst", "form_type": "2nd_person_singular"},
         {"form_text": "schläft", "form_type": "3rd_person_singular"},
         {"form_text": "schlief", "form_type": "past_tense"},
         {"form_text": "geschlafen", "form_type": "past_participle"},
     ]},

    {"lemma": "spielen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "jugar", "target_language": "es", "sense_order": 1}, {"text": "tocar", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Die Kinder spielen Fußball.", "translated_sentence": "Los niños juegan al fútbol."}],
     "alternative_forms": [
         {"form_text": "spiele", "form_type": "1st_person_singular"},
         {"form_text": "spielst", "form_type": "2nd_person_singular"},
         {"form_text": "spielt", "form_type": "3rd_person_singular"},
         {"form_text": "spielte", "form_type": "past_tense"},
         {"form_text": "gespielt", "form_type": "past_participle"},
     ]},

    {"lemma": "arbeiten", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "trabajar", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich arbeite als Lehrer.", "translated_sentence": "Trabajo como profesor."}],
     "alternative_forms": [
         {"form_text": "arbeite", "form_type": "1st_person_singular"},
         {"form_text": "arbeitest", "form_type": "2nd_person_singular"},
         {"form_text": "arbeitet", "form_type": "3rd_person_singular"},
         {"form_text": "arbeitete", "form_type": "past_tense"},
         {"form_text": "gearbeitet", "form_type": "past_participle"},
     ]},

    {"lemma": "kaufen", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "comprar", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich möchte Brot kaufen.", "translated_sentence": "Quiero comprar pan."}],
     "alternative_forms": [
         {"form_text": "kaufe", "form_type": "1st_person_singular"},
         {"form_text": "kaufst", "form_type": "2nd_person_singular"},
         {"form_text": "kauft", "form_type": "3rd_person_singular"},
         {"form_text": "kaufte", "form_type": "past_tense"},
         {"form_text": "gekauft", "form_type": "past_participle"},
     ]},

    {"lemma": "finden", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "encontrar", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich kann meinen Schlüssel nicht finden.", "translated_sentence": "No puedo encontrar mi llave."}],
     "alternative_forms": [
         {"form_text": "finde", "form_type": "1st_person_singular"},
         {"form_text": "findest", "form_type": "2nd_person_singular"},
         {"form_text": "findet", "form_type": "3rd_person_singular"},
         {"form_text": "fand", "form_type": "past_tense"},
         {"form_text": "gefunden", "form_type": "past_participle"},
     ]},

    {"lemma": "denken", "language": "de", "part_of_speech": "verb",
     "translations": [{"text": "pensar", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich denke an dich.", "translated_sentence": "Pienso en ti."}],
     "alternative_forms": [
         {"form_text": "denke", "form_type": "1st_person_singular"},
         {"form_text": "denkst", "form_type": "2nd_person_singular"},
         {"form_text": "denkt", "form_type": "3rd_person_singular"},
         {"form_text": "dachte", "form_type": "past_tense"},
         {"form_text": "gedacht", "form_type": "past_participle"},
     ]},

    # ── Adjectives ──
    {"lemma": "groß", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "grande", "target_language": "es", "sense_order": 1}, {"text": "alto", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Das Haus ist groß.", "translated_sentence": "La casa es grande."}],
     "alternative_forms": [{"form_text": "große", "form_type": "inflected"}, {"form_text": "großer", "form_type": "inflected"}, {"form_text": "größer", "form_type": "comparative"}, {"form_text": "größte", "form_type": "superlative"}]},

    {"lemma": "klein", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "pequeño", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Das Kind ist noch klein.", "translated_sentence": "El niño todavía es pequeño."}],
     "alternative_forms": [{"form_text": "kleine", "form_type": "inflected"}, {"form_text": "kleiner", "form_type": "comparative"}, {"form_text": "kleinste", "form_type": "superlative"}]},

    {"lemma": "gut", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "bueno", "target_language": "es", "sense_order": 1}, {"text": "bien", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Das Essen ist gut.", "translated_sentence": "La comida es buena."}],
     "alternative_forms": [{"form_text": "gute", "form_type": "inflected"}, {"form_text": "guter", "form_type": "inflected"}, {"form_text": "besser", "form_type": "comparative"}, {"form_text": "beste", "form_type": "superlative"}]},

    {"lemma": "schlecht", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "malo", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Das Wetter ist schlecht.", "translated_sentence": "El tiempo es malo."}],
     "alternative_forms": [{"form_text": "schlechte", "form_type": "inflected"}, {"form_text": "schlechter", "form_type": "comparative"}, {"form_text": "schlechteste", "form_type": "superlative"}]},

    {"lemma": "schön", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "bonito", "target_language": "es", "sense_order": 1}, {"text": "hermoso", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Die Stadt ist sehr schön.", "translated_sentence": "La ciudad es muy bonita."}],
     "alternative_forms": [{"form_text": "schöne", "form_type": "inflected"}, {"form_text": "schöner", "form_type": "comparative"}, {"form_text": "schönste", "form_type": "superlative"}]},

    {"lemma": "neu", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "nuevo", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich habe ein neues Auto.", "translated_sentence": "Tengo un coche nuevo."}],
     "alternative_forms": [{"form_text": "neue", "form_type": "inflected"}, {"form_text": "neuer", "form_type": "inflected"}, {"form_text": "neues", "form_type": "inflected"}]},

    {"lemma": "alt", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "viejo", "target_language": "es", "sense_order": 1}, {"text": "antiguo", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Wie alt bist du?", "translated_sentence": "¿Cuántos años tienes?"}],
     "alternative_forms": [{"form_text": "alte", "form_type": "inflected"}, {"form_text": "älter", "form_type": "comparative"}, {"form_text": "älteste", "form_type": "superlative"}]},

    {"lemma": "schnell", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "rápido", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Der Zug ist sehr schnell.", "translated_sentence": "El tren es muy rápido."}],
     "alternative_forms": [{"form_text": "schnelle", "form_type": "inflected"}, {"form_text": "schneller", "form_type": "comparative"}, {"form_text": "schnellste", "form_type": "superlative"}]},

    {"lemma": "langsam", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "lento", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Bitte sprechen Sie langsam.", "translated_sentence": "Por favor, hable despacio."}],
     "alternative_forms": [{"form_text": "langsame", "form_type": "inflected"}, {"form_text": "langsamer", "form_type": "comparative"}]},

    {"lemma": "wichtig", "language": "de", "part_of_speech": "adjective",
     "translations": [{"text": "importante", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Das ist sehr wichtig.", "translated_sentence": "Eso es muy importante."}],
     "alternative_forms": [{"form_text": "wichtige", "form_type": "inflected"}, {"form_text": "wichtiger", "form_type": "comparative"}, {"form_text": "wichtigste", "form_type": "superlative"}]},

    # ── Adverbs / Common words ──
    {"lemma": "heute", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "hoy", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Heute ist Montag.", "translated_sentence": "Hoy es lunes."}],
     "alternative_forms": []},

    {"lemma": "morgen", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "mañana", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Bis morgen!", "translated_sentence": "¡Hasta mañana!"}],
     "alternative_forms": []},

    {"lemma": "gestern", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "ayer", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Gestern war ich müde.", "translated_sentence": "Ayer estaba cansado."}],
     "alternative_forms": []},

    {"lemma": "immer", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "siempre", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Er kommt immer zu spät.", "translated_sentence": "Siempre llega tarde."}],
     "alternative_forms": []},

    {"lemma": "nie", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "nunca", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich war nie in Spanien.", "translated_sentence": "Nunca he estado en España."}],
     "alternative_forms": [{"form_text": "niemals", "form_type": "synonym"}]},

    {"lemma": "hier", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "aquí", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich bin hier.", "translated_sentence": "Estoy aquí."}],
     "alternative_forms": []},

    {"lemma": "dort", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "allí", "target_language": "es", "sense_order": 1}, {"text": "ahí", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Das Buch ist dort.", "translated_sentence": "El libro está allí."}],
     "alternative_forms": []},

    {"lemma": "sehr", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "muy", "target_language": "es", "sense_order": 1}, {"text": "mucho", "target_language": "es", "sense_order": 2}],
     "examples": [{"source_sentence": "Das ist sehr gut.", "translated_sentence": "Eso es muy bueno."}],
     "alternative_forms": []},

    {"lemma": "auch", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "también", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich komme auch.", "translated_sentence": "Yo también vengo."}],
     "alternative_forms": []},

    {"lemma": "schon", "language": "de", "part_of_speech": "adverb",
     "translations": [{"text": "ya", "target_language": "es", "sense_order": 1}],
     "examples": [{"source_sentence": "Ich bin schon fertig.", "translated_sentence": "Ya he terminado."}],
     "alternative_forms": []},

    # ── Spanish → German entries ──
    {"lemma": "casa", "language": "es", "part_of_speech": "noun", "gender": "f",
     "translations": [{"text": "Haus", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "Mi casa es grande.", "translated_sentence": "Mein Haus ist groß."}],
     "alternative_forms": [{"form_text": "casas", "form_type": "plural"}]},

    {"lemma": "libro", "language": "es", "part_of_speech": "noun", "gender": "m",
     "translations": [{"text": "Buch", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "Leo un libro.", "translated_sentence": "Ich lese ein Buch."}],
     "alternative_forms": [{"form_text": "libros", "form_type": "plural"}]},

    {"lemma": "ir", "language": "es", "part_of_speech": "verb",
     "translations": [{"text": "gehen", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "Voy a la escuela.", "translated_sentence": "Ich gehe zur Schule."}],
     "alternative_forms": [{"form_text": "voy", "form_type": "1st_person_singular"}, {"form_text": "vas", "form_type": "2nd_person_singular"}, {"form_text": "va", "form_type": "3rd_person_singular"}, {"form_text": "fue", "form_type": "past_tense"}, {"form_text": "ido", "form_type": "past_participle"}]},

    {"lemma": "hacer", "language": "es", "part_of_speech": "verb",
     "translations": [{"text": "machen", "target_language": "de", "sense_order": 1}, {"text": "tun", "target_language": "de", "sense_order": 2}],
     "examples": [{"source_sentence": "¿Qué haces?", "translated_sentence": "Was machst du?"}],
     "alternative_forms": [{"form_text": "hago", "form_type": "1st_person_singular"}, {"form_text": "haces", "form_type": "2nd_person_singular"}, {"form_text": "hace", "form_type": "3rd_person_singular"}, {"form_text": "hizo", "form_type": "past_tense"}, {"form_text": "hecho", "form_type": "past_participle"}]},

    {"lemma": "comer", "language": "es", "part_of_speech": "verb",
     "translations": [{"text": "essen", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "Quiero comer.", "translated_sentence": "Ich möchte essen."}],
     "alternative_forms": [{"form_text": "como", "form_type": "1st_person_singular"}, {"form_text": "comes", "form_type": "2nd_person_singular"}, {"form_text": "comió", "form_type": "past_tense"}, {"form_text": "comido", "form_type": "past_participle"}]},

    {"lemma": "hablar", "language": "es", "part_of_speech": "verb",
     "translations": [{"text": "sprechen", "target_language": "de", "sense_order": 1}, {"text": "reden", "target_language": "de", "sense_order": 2}],
     "examples": [{"source_sentence": "¿Hablas alemán?", "translated_sentence": "Sprichst du Deutsch?"}],
     "alternative_forms": [{"form_text": "hablo", "form_type": "1st_person_singular"}, {"form_text": "hablas", "form_type": "2nd_person_singular"}, {"form_text": "habla", "form_type": "3rd_person_singular"}, {"form_text": "habló", "form_type": "past_tense"}, {"form_text": "hablado", "form_type": "past_participle"}]},

    {"lemma": "agua", "language": "es", "part_of_speech": "noun", "gender": "f",
     "translations": [{"text": "Wasser", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "Bebo agua.", "translated_sentence": "Ich trinke Wasser."}],
     "alternative_forms": []},

    {"lemma": "amigo", "language": "es", "part_of_speech": "noun", "gender": "m",
     "translations": [{"text": "Freund", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "Él es mi mejor amigo.", "translated_sentence": "Er ist mein bester Freund."}],
     "alternative_forms": [{"form_text": "amigos", "form_type": "plural"}, {"form_text": "amiga", "form_type": "feminine"}]},

    {"lemma": "grande", "language": "es", "part_of_speech": "adjective",
     "translations": [{"text": "groß", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "La casa es grande.", "translated_sentence": "Das Haus ist groß."}],
     "alternative_forms": [{"form_text": "grandes", "form_type": "plural"}, {"form_text": "gran", "form_type": "apocopated"}]},

    {"lemma": "bueno", "language": "es", "part_of_speech": "adjective",
     "translations": [{"text": "gut", "target_language": "de", "sense_order": 1}],
     "examples": [{"source_sentence": "El libro es bueno.", "translated_sentence": "Das Buch ist gut."}],
     "alternative_forms": [{"form_text": "buena", "form_type": "feminine"}, {"form_text": "buenos", "form_type": "plural"}, {"form_text": "buen", "form_type": "apocopated"}, {"form_text": "mejor", "form_type": "comparative"}]},
]


async def import_seed_data():
    """Import the built-in seed data into MongoDB."""
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    words_col = db.words

    # Check if data already exists
    count = await words_col.count_documents({})
    if count > 0:
        print(f"⚠️  Database already has {count} entries. Skipping seed import.")
        print("   To reimport, drop the 'words' collection first.")
        client.close()
        return

    # Add normalized_form to all entries
    for entry in SEED_DATA:
        entry["normalized_form"] = normalize_umlauts(entry["lemma"].lower())

    result = await words_col.insert_many(SEED_DATA)
    print(f"✅ Imported {len(result.inserted_ids)} seed entries")

    # Create indexes
    await words_col.create_index([("lemma", "text"), ("normalized_form", "text")], name="text_search")
    await words_col.create_index([("language", 1), ("normalized_form", 1)], name="lang_normalized")
    await words_col.create_index([("alternative_forms.form_text", 1)], name="alt_forms")
    await words_col.create_index([("language", 1), ("lemma", 1)], name="lang_lemma")
    print("✅ Indexes created")

    client.close()
    print("🎉 Seed data import complete!")


async def import_freedict(filepath: str, source_lang: str = "de", target_lang: str = "es"):
    """Import from a FreeDict TEI XML file. Supports any language pair."""
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    words_col = db.words

    print(f"📖 Parsing FreeDict file: {filepath}")
    tree = ET.parse(filepath)
    root = tree.getroot()

    # TEI namespace
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    entries = root.findall(".//tei:entry", ns)
    if not entries:
        entries = root.findall(".//entry")

    print(f"   Found {len(entries)} raw entries")

    # Gender mapping from TEI to our schema
    gender_map = {"fem": "f", "masc": "m", "neut": "n"}
    # POS mapping from TEI abbreviations
    pos_map = {
        "n": "noun", "v": "verb", "adj": "adjective", "adv": "adverb",
        "prep": "preposition", "conj": "conjunction", "pron": "pronoun",
        "interj": "interjection", "num": "numeral", "suffix": "suffix",
        "prefix": "prefix", "art": "article", "part": "particle",
    }

    docs = []
    skipped = 0
    for entry in entries:
        # Extract headword (use 'is None' — XML elements are falsy when empty!)
        orth = entry.find(".//tei:orth", ns)
        if orth is None:
            orth = entry.find(".//orth")
        if orth is None or not orth.text:
            skipped += 1
            continue

        lemma = orth.text.strip()

        # Extract pronunciation
        pron_el = entry.find(".//tei:pron", ns)
        if pron_el is None:
            pron_el = entry.find(".//pron")
        pronunciation = pron_el.text.strip() if pron_el is not None and pron_el.text else None

        # Extract POS
        pos_el = entry.find(".//tei:pos", ns)
        if pos_el is None:
            pos_el = entry.find(".//pos")
        raw_pos = pos_el.text.strip() if pos_el is not None and pos_el.text else "unknown"
        pos = pos_map.get(raw_pos, raw_pos)

        # Extract gender (for nouns)
        gen_el = entry.find(".//tei:gen", ns)
        if gen_el is None:
            gen_el = entry.find(".//gen")
        gender = None
        if gen_el is not None and gen_el.text:
            gender = gender_map.get(gen_el.text.strip(), None)

        # Extract translations — find <cit type="trans"> elements
        translations = []
        cit_elements = entry.findall(".//tei:cit[@type='trans']", ns)
        if len(cit_elements) == 0:
            cit_elements = entry.findall(".//tei:cit", ns)
        if len(cit_elements) == 0:
            cit_elements = entry.findall(".//cit")
        for i, cit in enumerate(cit_elements):
            quote = cit.find("tei:quote", ns)
            if quote is None:
                quote = cit.find("quote")
            if quote is not None and quote.text:
                translations.append({
                    "text": quote.text.strip(),
                    "target_language": "es",
                    "sense_order": i + 1,
                })

        if not translations:
            skipped += 1
            continue

        doc = {
            "lemma": lemma,
            "language": source_lang,
            "part_of_speech": pos,
            "gender": gender,
            "plural_form": None,
            "pronunciation": pronunciation,
            "normalized_form": normalize_umlauts(lemma.lower()),
            "translations": [{**t, "target_language": target_lang} for t in translations],
            "examples": [],
            "alternative_forms": generate_alternative_forms(lemma, source_lang),
        }
        docs.append(doc)

    print(f"   Parsed {len(docs)} valid entries ({skipped} skipped)")

    if docs:
        # Batch insert in chunks of 1000
        batch_size = 1000
        total_inserted = 0
        for i in range(0, len(docs), batch_size):
            batch = docs[i:i + batch_size]
            result = await words_col.insert_many(batch)
            total_inserted += len(result.inserted_ids)
            print(f"   ⏳ Inserted {total_inserted}/{len(docs)}...")

        # Recreate indexes
        await words_col.create_index([("lemma", "text"), ("normalized_form", "text")], name="text_search")
        await words_col.create_index([("language", 1), ("normalized_form", 1)], name="lang_normalized")
        await words_col.create_index([("alternative_forms.form_text", 1)], name="alt_forms")
        await words_col.create_index([("language", 1), ("lemma", 1)], name="lang_lemma")
        print(f"✅ Imported {total_inserted} entries from FreeDict")
        print("✅ Indexes recreated")
    else:
        print("⚠️  No entries found in FreeDict file")

    client.close()


async def generate_reverse_entries():
    """Generate ES→DE entries from existing DE→ES entries."""
    client = AsyncIOMotorClient(MONGODB_URI, tlsCAFile=certifi.where())
    db = client[DB_NAME]
    words_col = db.words

    print("🔄 Generating reverse entries (ES→DE) from existing DE→ES data...")

    # Find all DE entries that have ES translations
    cursor = words_col.find({"language": "de", "translations.target_language": "es"})
    reverse_docs = []
    existing_es = set()

    # Get already-existing ES lemmas to avoid duplicates
    async for doc in words_col.find({"language": "es"}, {"lemma": 1}):
        existing_es.add(doc["lemma"].lower())

    print(f"   Found {len(existing_es)} existing ES entries")

    async for doc in cursor:
        for trans in doc.get("translations", []):
            if trans.get("target_language") != "es":
                continue
            es_word = trans["text"].strip()
            if es_word.lower() in existing_es:
                continue
            existing_es.add(es_word.lower())

            reverse_doc = {
                "lemma": es_word,
                "language": "es",
                "part_of_speech": doc.get("part_of_speech", "unknown"),
                "gender": None,
                "plural_form": None,
                "pronunciation": None,
                "normalized_form": normalize_umlauts(es_word.lower()),
                "translations": [{
                    "text": doc["lemma"],
                    "target_language": "de",
                    "sense_order": 1,
                }],
                "examples": [],
                "alternative_forms": generate_alternative_forms(es_word, "es"),
            }
            reverse_docs.append(reverse_doc)

    if reverse_docs:
        batch_size = 1000
        total = 0
        for i in range(0, len(reverse_docs), batch_size):
            batch = reverse_docs[i:i + batch_size]
            result = await words_col.insert_many(batch)
            total += len(result.inserted_ids)
            print(f"   ⏳ Inserted {total}/{len(reverse_docs)}...")
        print(f"✅ Generated {total} reverse ES→DE entries")
    else:
        print("⚠️  No new reverse entries to generate")

    client.close()


async def main():
    parser = argparse.ArgumentParser(description="Import dictionary data into MongoDB")
    parser.add_argument("--freedict", type=str, help="Path to FreeDict TEI XML file (deu-spa)")
    parser.add_argument("--freedict-spa", type=str, help="Path to FreeDict TEI XML file (spa-deu)")
    parser.add_argument("--generate-reverse", action="store_true", help="Generate ES→DE from existing DE→ES")
    args = parser.parse_args()

    if not MONGODB_URI:
        print("❌ MONGODB_URI not set. Copy .env.example to .env and fill in your connection string.")
        sys.exit(1)

    if args.freedict:
        await import_freedict(args.freedict, source_lang="de", target_lang="es")
    elif args.freedict_spa:
        await import_freedict(args.freedict_spa, source_lang="es", target_lang="de")
    elif args.generate_reverse:
        await generate_reverse_entries()
    else:
        print("🌱 Importing seed data (built-in starter dictionary)...")
        await import_seed_data()


if __name__ == "__main__":
    asyncio.run(main())
