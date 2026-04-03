# Gamified Data Consolidator

AI-native SaaS for consolidating messy business data into a unified schema.
Local-first architecture (LLM calls are the only cloud dependency).

## Structure
- `backend/` FastAPI API and background services
- `frontend/` React UI
- `docs/` project plans and specifications (ignored by git)
- `test/` test scripts (ignored by git)

## Quick start (Windows)
1. Create and activate the virtual environment:
   - `python -m venv venv`
   - `venv\Scripts\activate`
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Create `.env` from `.env.example` and fill in values.
4. Run the API:
   - `uvicorn backend.app.main:app --reload`

## Environment variables
See `.env.example` for required keys and placeholders.
Use `DATABASE_URL` for your PostgreSQL connection string.
Use `AZURE_OPENAI_DEPLOYMENT_EMBEDDINGS` for embedding generation.

## Database migrations (Alembic)
- Upgrade to latest: `alembic upgrade head`
- Create a new migration: `alembic revision --autogenerate -m "your message"`## Postgres vector support
- Ensure the `vector` extension is available (pgvector) for schema mapping embeddings.

## PDF OCR dependencies (Windows)
- Install Tesseract OCR and set `TESSERACT_CMD` to the full path, e.g. `C:\Program Files\Tesseract-OCR\tesseract.exe`
- Install Poppler for Windows and set `POPPLER_PATH` to its `bin` folder
