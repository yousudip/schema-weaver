<div align="center">

# Schema Weaver

**AI-native data consolidation — from messy files to unified schemas, automatically.**

*Upload a PDF invoice, a scattered Excel sheet, or a raw CSV dump. Schema Weaver reads it, understands it, maps it, and hands you clean, structured data — all without writing a single line of ETL code.*

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react)](https://react.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791?style=flat-square&logo=postgresql)](https://github.com/pgvector/pgvector)
[![Azure OpenAI](https://img.shields.io/badge/Azure-OpenAI-0089D6?style=flat-square&logo=microsoftazure)](https://azure.microsoft.com/en-us/products/ai-services/openai-service)
[![Docker](https://img.shields.io/badge/Docker-Sandbox-2496ED?style=flat-square&logo=docker)](https://www.docker.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## What Is Schema Weaver?

Modern businesses are drowning in data fragmentation. Financial reports live in Excel, invoices arrive as PDFs, and customer records are dumped as raw CSVs — each with different column names, date formats, and conventions. Consolidating them into a single schema means weeks of manual mapping, brittle ETL scripts, and constant rework whenever a source changes.

**Schema Weaver eliminates this entirely.**

It acts as an intelligent agent: it reads your file, infers its semantic structure using an LLM, generates vector embeddings for each column, and matches them to your target schema — automatically. Human-in-the-loop controls let you confirm or correct AI suggestions before data is written. All transformation code runs inside a secure Docker sandbox, so nothing untrusted ever touches your host.

The result: data onboarding that used to take days now takes minutes.

---

## Demo

https://github.com/user-attachments/assets/6ec12f10-a934-4cc5-8e30-1dd0c44581d5

---

## Key Features

| | Feature | Description |
|---|---|---|
| **AI Schema Inference** | | GPT-5 analyzes your file and generates a full JSON schema with column types, descriptions, and confidence scores |
| **Semantic Column Matching** | | Vector embeddings (pgvector) match source columns to target fields by *meaning*, not just name — "Emp_ID" maps to "user_id" automatically |
| **Multi-Format Parsing** | | Native support for PDF (with OCR), Excel (.xlsx/.xls), and CSV — including scanned documents via Tesseract |
| **Secure Code Execution** | | AI-generated transformation scripts run in an isolated Docker container with no network access, memory caps, and timeout enforcement |
| **Self-Healing AI** | | If generated code throws an error, the LLM receives the traceback and fixes it automatically (reflexion loop, up to 3 attempts) |
| **Data Quality Reports** | | After each execution, a quality report scores fill rates, flags partial/null columns, and records validation attempt history |
| **Multi-File Jobs** | | Group related files under a single named job (e.g. "Invoice Processing Q1 2026") and process them all as a batch |
| **AI-Powered Consolidation** | | "Export All" merges all processed files in a job into a single unified CSV — the LLM maps disparate column names to a canonical schema automatically |
| **Real-Time Streaming** | | Server-Sent Events (SSE) push live progress updates for every long-running operation — no polling, no stale spinners |
| **Gamified UX** | | Onboarding is designed as an interactive, step-by-step experience with visual progress feedback |
| **Local-First** | | Entire stack runs on your machine. Azure OpenAI is the only cloud dependency |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        React Frontend                        │
│   File Upload · SSE Streams · Schema Review · Batch Jobs    │
└──────────────────────────┬──────────────────────────────────┘
                           │  HTTP / SSE
┌──────────────────────────▼──────────────────────────────────┐
│                      FastAPI Backend                         │
│                                                             │
│  ┌─────────────┐   ┌──────────────┐   ┌─────────────────┐  │
│  │  API Routes  │   │ Worker Queue │   │   LLM Engine    │  │
│  │  /upload     │──▶│  (async)     │──▶│  Schema Infer   │  │
│  │  /infer      │   │  Task Exec   │   │  Code Generate  │  │
│  │  /stream     │   └──────────────┘   │  Self-Healing   │  │
│  │  /consolidate│                      │  Col. Mapping   │  │
│  └─────────────┘                       └────────┬────────┘  │
│                                                 │           │
│  ┌──────────────────────┐   ┌──────────────────▼────────┐  │
│  │   PostgreSQL + pgvec │   │    Docker Sandbox          │  │
│  │   Jobs · Tasks       │   │    Isolated Python env     │  │
│  │   JobFiles · Analysis│   │    No network · RAM cap    │  │
│  └──────────────────────┘   └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │  Azure OpenAI API
                    ┌──────▼──────┐
                    │  GPT-5      │  Schema inference · Code gen · Consolidation
                    │  GPT-5 mini │  Classification · Mapping
                    │  Embeddings │  Vector search
                    └─────────────┘
```

---

## Tech Stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com) — async Python API framework
- [PostgreSQL](https://www.postgresql.org) + [pgvector](https://github.com/pgvector/pgvector) — relational store + vector similarity search
- [SQLAlchemy](https://www.sqlalchemy.org) + [Alembic](https://alembic.sqlalchemy.org) — ORM and migrations
- [Azure OpenAI](https://azure.microsoft.com/en-us/products/ai-services/openai-service) — GPT-5, GPT-5 mini, text-embedding-3-small
- [Docker](https://www.docker.com) — sandboxed code execution
- [pdfplumber](https://github.com/jsvine/pdfplumber) + [Camelot](https://camelot-py.readthedocs.io) + [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) — PDF parsing
- [Pandas](https://pandas.pydata.org) + [Openpyxl](https://openpyxl.readthedocs.io) — spreadsheet processing

**Frontend**
- [React 19](https://react.dev) + [TypeScript](https://www.typescriptlang.org)
- [Vite](https://vitejs.dev) — build tooling with HMR
- Server-Sent Events — real-time status streaming for all long-running operations

---

## Prerequisites

Before you begin, ensure you have the following installed:

- **Python 3.11+**
- **Node.js 18+** and npm
- **PostgreSQL 15+** with the [pgvector extension](https://github.com/pgvector/pgvector)
- **Docker Desktop** (for the code execution sandbox)
- **Tesseract OCR** — [Windows installer](https://github.com/UB-Mannheim/tesseract/wiki)
- **Poppler** — [Windows binaries](https://github.com/oschwartz10612/poppler-windows/releases)
- An **Azure OpenAI** resource with deployments for GPT-5, GPT-5 mini, and an embeddings model

---

## Installation & Setup

### 1. Clone the repository

```bash
git clone https://github.com/yousudip/schema-weaver.git
cd schema-weaver
```

### 2. Backend setup

```bash
# Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

# Install Python dependencies
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in all values:

```env
# PostgreSQL connection string
DATABASE_URL=postgresql://user:password@localhost:5432/schema_weaver

# Local storage path for uploaded files
LOCAL_STORAGE_DIR=storage

# Azure OpenAI — your resource endpoint and API key
OPENAI_ENDPOINT=https://your-resource.openai.azure.com
OPENAI_API_KEY=your-api-key-here

# Deployment names from your Azure OpenAI resource
OPENAI_DEPLOYMENT_GPT5=gpt-5
OPENAI_DEPLOYMENT_GPT5_MINI=gpt-5-mini
OPENAI_DEPLOYMENT_EMBEDDINGS=text-embedding-3-small

# Docker sandbox configuration
SANDBOX_IMAGE=gdc-sandbox:local
SANDBOX_CPU=1
SANDBOX_MEMORY_MB=512

# OCR dependencies (Windows paths)
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\Program Files\poppler\Library\bin

# Frontend origin (for CORS)
CORS_ORIGINS=http://localhost:5173
```

### 4. Set up the database

```bash
# Enable pgvector in PostgreSQL (run once in psql)
# CREATE EXTENSION IF NOT EXISTS vector;

# Run all migrations
alembic upgrade head
```

### 5. Build the Docker sandbox image

```bash
docker build -t gdc-sandbox:local ./backend/sandbox
```

### 6. Start the backend

```bash
uvicorn backend.app.main:app --reload
```

The API will be running at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

### 7. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The UI will be running at `http://localhost:5173`.

---

## User Guide

### Single-File Workflow

#### Step 1 — Upload a file

From the home screen, click **Upload File** and select a PDF, Excel (.xlsx/.xls), or CSV file. Schema Weaver accepts messy, real-world files — inconsistent headers, merged cells, and scanned PDFs are all handled.

Once uploaded, a **Job** is created and you are redirected to the job detail view. A real-time status bar shows the processing progress.

#### Step 2 — File parsing

Schema Weaver automatically detects the file type and chooses the best parsing strategy:

| File Type | Strategy |
|---|---|
| CSV | Direct pandas parse with delimiter detection |
| Excel | Openpyxl with multi-sheet support |
| Native PDF | pdfplumber / Camelot for layout-aware table extraction |
| Scanned PDF | Tesseract OCR → text reconstruction → table inference |

#### Step 3 — AI schema inference

Click **Infer Schema** to trigger LLM analysis. GPT-5 examines a representative sample of your data (using stratified sampling for large files) and returns a suggested column name, data type, plain-English description, and confidence score for each column. The inference uses a **reflexion loop** — if the model's output fails Pydantic validation, the error is automatically fed back for self-correction (up to 3 attempts).

#### Step 4 — Review and confirm the schema

The inferred schema is displayed as an editable table. Accept, edit, or remove columns as needed, then click **Confirm Schema** to lock it in.

#### Step 5 — Semantic column matching

Click **Generate Embeddings** to create vector representations of your confirmed columns, stored in PostgreSQL via pgvector. Use the **Match Schema** panel to find semantically similar columns across previously processed files (cosine distance ranking).

#### Step 6 — Data transformation & execution

Click **Execute** to generate a Python transformation script and run it inside the Docker sandbox:

- Network access is disabled
- Memory is capped at the configured limit
- Execution timeout is enforced
- All imports are validated against a whitelist before execution

If the script fails, the traceback is sent back to the LLM for automated debugging and repair. Up to 3 validation attempts are made automatically.

#### Step 7 — Data Quality Report

After successful execution, a **Data Quality Report** is shown for each file:

- Overall fill rate percentage
- Per-column null/partial/clean status
- Validation loop attempt history
- Pass/fail badge

#### Step 8 — Download

Click **Download** on any executed file to save its cleaned CSV output.

---

### Multi-File Job Workflow

Multi-file jobs let you group related files under a shared business purpose and consolidate them all into a single unified dataset.

#### Creating a job

Click **+ New** in the sidebar to create a named job (e.g. *"Invoice processing Q1 2026"*). Then use **+ Add File** to upload multiple files into the job one by one.

#### Batch processing

Click **Process All** to run the full pipeline (extract → infer → generate → execute → validate) on all files in the job simultaneously. Each file streams its own progress independently via SSE.

#### Consolidation — Export All

Once all files have been executed successfully, click **Export All** to consolidate them into a single unified CSV:

1. The LLM analyzes the schemas of all processed files and produces a **canonical column mapping** — mapping each file's own column names to a shared set of unified column names.
2. All output CSVs are read, columns are renamed to canonical names, and the data is concatenated.
3. A `_source_file` column is appended to each row identifying its origin file.
4. The merged result is saved as `consolidated.csv` in the job's storage directory.
5. A **Consolidated Output** panel appears in the UI showing:
   - File count, row count, and column count
   - An expandable column mapping table showing how each file's columns map to the canonical schema
   - A data preview of the first rows
   - A **⬇ Download CSV** button

The consolidation result is persisted in the database and automatically restored when you revisit the job.

---

## API Reference

The full interactive API documentation is available at `http://localhost:8000/docs` when the backend is running.

### Job Management

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/upload` | Upload a file and create a new single-file job |
| `POST` | `/api/v1/jobs/new` | Create a new multi-file job with a business purpose |
| `GET` | `/api/v1/jobs` | List all recent jobs |
| `GET` | `/api/v1/jobs/{job_id}` | Get full job details including persisted analysis |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete a job and all associated files |

### Single-File Pipeline

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/v1/jobs/{job_id}/status/stream` | SSE stream for real-time job status |
| `POST` | `/api/v1/jobs/{job_id}/infer` | Trigger LLM schema inference |
| `POST` | `/api/v1/jobs/{job_id}/schema/select` | Confirm the selected schema |
| `POST` | `/api/v1/jobs/{job_id}/schema/embeddings` | Generate pgvector embeddings for columns |
| `POST` | `/api/v1/schema/match` | Search for semantically similar schemas |
| `POST` | `/api/v1/jobs/{job_id}/generate` | Generate transformation code |
| `POST` | `/api/v1/jobs/{job_id}/execute/stream` | Execute transformation code (SSE stream) |
| `GET` | `/api/v1/jobs/{job_id}/download` | Download the cleaned output CSV |

### Multi-File Job Pipeline

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/jobs/{job_id}/files` | Upload a file into an existing multi-file job |
| `GET` | `/api/v1/jobs/{job_id}/files` | List all files in a job with per-file status |
| `DELETE` | `/api/v1/jobs/{job_id}/files/{file_id}` | Remove a file from a job |
| `POST` | `/api/v1/jobs/{job_id}/files/{file_id}/extract/stream` | Extract & parse raw file (SSE stream) |
| `POST` | `/api/v1/jobs/{job_id}/files/{file_id}/infer` | Run LLM schema inference on a file |
| `POST` | `/api/v1/jobs/{job_id}/files/{file_id}/schema/select` | Confirm schema for a file |
| `POST` | `/api/v1/jobs/{job_id}/files/{file_id}/generate` | Generate transformation code for a file |
| `POST` | `/api/v1/jobs/{job_id}/files/{file_id}/execute/stream` | Execute transformation code for a file (SSE stream) |
| `GET` | `/api/v1/jobs/{job_id}/files/{file_id}/download` | Download individual file's cleaned output CSV |
| `POST` | `/api/v1/jobs/{job_id}/consolidate/stream` | Consolidate all executed files into one CSV (SSE stream) |
| `GET` | `/api/v1/jobs/{job_id}/consolidate/download` | Download the final consolidated CSV |

---

## Project Structure

```
schema-weaver/
├── backend/
│   ├── app/
│   │   ├── api/routes/
│   │   │   ├── file_pipeline.py  # Per-file pipeline: extract, infer, generate, execute, consolidate
│   │   │   ├── jobs.py           # Multi-file job CRUD and file management
│   │   │   ├── tasks.py          # Single-file job pipeline and task queue
│   │   │   ├── stream.py         # SSE status streaming
│   │   │   └── health.py         # Health check
│   │   ├── core/                 # Config and LLM client
│   │   ├── llm/                  # Schema inference, embeddings, consolidation mapping
│   │   ├── parsers/              # PDF, Excel, CSV parsers
│   │   ├── sandbox/              # Docker session manager
│   │   ├── security/             # AST analyzer and audit logging
│   │   ├── tasks/                # Background task handlers
│   │   ├── db.py                 # Database connection
│   │   ├── db_models.py          # SQLAlchemy models (Job, Task, JobFile)
│   │   ├── job_store.py          # Job persistence layer
│   │   ├── main.py               # FastAPI app entry point
│   │   └── worker_queue.py       # Async task queue
│   └── sandbox/
│       └── Dockerfile            # Sandbox container image
├── frontend/
│   └── src/
│       ├── App.tsx               # Main React component (single-file + multi-file workflows)
│       ├── App.css               # Styles (responsive grid, panels, quality reports)
│       └── main.tsx              # Entry point
├── alembic/                      # Database migrations
├── .env.example                  # Environment variable template
├── requirements.txt              # Python dependencies
└── README.md
```

---

## Technical Notes

### Non-Blocking Async Architecture

All blocking operations in the consolidation pipeline — database reads, LLM API calls, pandas I/O, and database commits — run in a thread pool via `asyncio.to_thread`. This keeps the FastAPI event loop free during long-running LLM calls (which can take 30+ seconds), so the server remains responsive for all other requests while consolidation is in progress.

Database sessions are always opened, used, and closed within the same synchronous function passed to `to_thread`. Sessions are never held open across thread boundaries or across LLM calls.

### SSE Streaming

Every long-running operation (file extraction, code execution, consolidation) uses Server-Sent Events via FastAPI's `StreamingResponse`. The frontend consumes these streams with the Fetch API's `ReadableStream`, parsing `event:` / `data:` lines from the raw byte stream. This provides granular progress feedback without polling.

### Data Quality Validation Loop

After each code execution, the generated script is validated against a quality threshold. If the fill rate is below the acceptable level or critical columns are null, the LLM receives the quality report as additional context and regenerates the transformation code. Up to 3 attempts are made before the result is accepted as-is.

### PostgreSQL JSON Safety

Pandas `DataFrame.to_dict(orient='records')` can produce Python `float('nan')` values, which serialize to the unquoted token `NaN` — valid Python but invalid JSON, rejected by PostgreSQL's JSON column type. All values destined for JSON columns are sanitized before commit: `float('nan')` and `float('inf')` are replaced with `None`.

### SQLAlchemy JSON Mutation Tracking

SQLAlchemy does not automatically detect in-place mutations to JSON columns. After updating a dict stored in a JSON column, `flag_modified(obj, 'column_name')` is called explicitly to mark the field dirty before `session.commit()`.

---

## Roadmap

- [x] File upload and job lifecycle management
- [x] Multi-format parsing (PDF, Excel, CSV) with OCR
- [x] LLM schema inference with reflexion loop
- [x] pgvector semantic column matching
- [x] Docker sandbox for secure code execution
- [x] Real-time SSE status streaming
- [x] React frontend with live job status
- [x] AI-generated transformation scripts + self-healing sandbox execution
- [x] Data Quality Reports with fill-rate scoring and validation loop history
- [x] Multi-file jobs with batch processing ("Process All")
- [x] AI-powered cross-file consolidation with canonical column mapping ("Export All")
- [x] Per-file and consolidated CSV download
- [x] Consolidation result persisted in DB and restored on job reload
- [x] Gamified step-by-step UX with progress feedback
- [ ] Visual schema mapper (React Flow node editor)
- [ ] Email ingestion (IMAP / MAPI)
- [ ] User authentication and multi-tenancy
- [ ] Cloud deployment (AWS / Azure)

---

## Contributing

Contributions are welcome. Please open an issue to discuss what you'd like to change before submitting a pull request.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add your feature'`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">
Built with FastAPI · React · Azure OpenAI · pgvector · Docker
</div>
