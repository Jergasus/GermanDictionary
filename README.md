# Wörterbuch — Diccionario Alemán ↔ Español

Un diccionario alemán-español rápido, limpio, sin anuncios, y optimizado para móvil.

## Tech Stack

- **Frontend**: Next.js 15 + React + TailwindCSS
- **Backend**: FastAPI (Python)
- **Base de datos**: MongoDB Atlas
- **NLP**: simplemma (lemmatización) + rapidfuzz (fuzzy matching)

## Requisitos

- Docker + Docker Compose (**recomendado**), o:
- Node.js 18+ y Python 3.11+
- Una cuenta de MongoDB Atlas (tier gratuito funciona)

## 🐳 Inicio rápido con Docker (un solo comando)

```bash
# 1. Configura tu MongoDB Atlas URI en el .env de la raíz
#    (ya debería estar configurado si seguiste el setup)

# 2. Arranca todo
docker compose up --build

# ¡Listo! Abre http://localhost:3000
```

Para parar los servicios:

```bash
docker compose down
```

## Setup

### 1. Backend

```bash
cd backend

# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar MongoDB
cp .env.example .env
# Edita .env con tu MongoDB Atlas URI

# Importar datos de prueba
python import_data.py

# Iniciar servidor
uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend

# Instalar dependencias
npm install

# Iniciar dev server
npm run dev
```

### 3. Usar

Abre [http://localhost:3000](http://localhost:3000) en tu navegador.

## Características

- 🔍 **Búsqueda instantánea** con debounce
- 🔗 **Lemmatización** — busca "geht" y encuentra "gehen"
- 🔤 **Normalización de umlauts** — busca "schueler" y encuentra "Schüler"
- 📝 **Fuzzy matching** — tolerancia a errores tipográficos
- 🗣️ **Pronunciación** — botón TTS para escuchar palabras
- 📱 **Mobile-first** — diseño optimizado para móvil
- 🔄 **Bidireccional** — DE→ES y ES→DE
- 🏷️ **Género visual** — badges de color para der/die/das

## API Endpoints

| Método | Endpoint                        | Descripción        |
| ------ | ------------------------------- | ------------------ |
| GET    | `/api/search?q=gehen&lang=de`   | Búsqueda principal |
| GET    | `/api/word/{id}`                | Detalle de palabra |
| GET    | `/api/suggestions?q=ge&lang=de` | Autocompletar      |
| GET    | `/api/health`                   | Health check       |
