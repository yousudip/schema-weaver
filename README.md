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

## Key Features

| | Feature | Description |
|---|---|---|
| **AI Schema Inference** | | GPT-5 analyzes your file and generates a full JSON schema with column types, descriptions, and confidence scores |
| **Semantic Column Matching** | | Vector embeddings (pgvector) match source columns to target fields by *meaning*, not just name — "Emp_ID" maps to "user_id" automatically |
| **Multi-Format Parsing** | | Native support for PDF (with OCR), Excel (.xlsx/.xls), and CSV — including scanned documents via Tesseract |
| **Secure Code Execution** | | AI-generated transformation scripts run in an isolated Docker container with no network access, memory caps, and timeout enforcement |
| **Real-Time Streaming** | | Server-Sent Events (SSE) push live progress updates to the UI — no polling, no stale spinners |
| **Self-Healing AI** | | If generated code throws an error, the LLM receives the traceback and fixes it automatically (reflexion loop) |
| **Gamified UX** | | Onboarding is designed as an interactive, step-by-step experience rather than a form-filling chore |
| **Local-First** | | Entire stack runs on your machine. Azure OpenAI is the only cloud dependency |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        React Frontend                        │
│         File Upload  ·  SSE Stream  ·  Schema Review        │
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
│  └─────────────┘                       └────────┬────────┘  │
│                                                 │           │
│  ┌──────────────────────┐   ┌──────────────────▼────────┐  │
│  │   PostgreSQL + pgvec │   │    Docker Sandbox          │  │
│  │   Jobs · Tasks       │   │    Isolated Python env     │  │
│  │   Schema Vectors     │   │    No network · RAM cap    │  │
│  └──────────────────────┘   └───────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                           │  Azure OpenAI API
                    ┌──────▼──────┐
                    │  GPT-5      │  Schema inference · Code gen
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
- [Vite](https://vitejs.dev) — build tooling
- Server-Sent Events — real-time status streaming

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
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_API_KEY=your-api-key-here

# Deployment names from your Azure OpenAI resource
AZURE_OPENAI_DEPLOYMENT_GPT5=gpt-5
AZURE_OPENAI_DEPLOYMENT_GPT5_MINI=gpt-5-mini
AZURE_OPENAI_DEPLOYMENT_EMBEDDINGS=text-embedding-3-small

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

### Step 1 — Upload a file

From the home screen, click **Upload File** and select a PDF, Excel (.xlsx/.xls), or CSV file. Schema Weaver accepts messy, real-world files — inconsistent headers, merged cells, and scanned PDFs are all handled.

Once uploaded, a **Job** is created and you are redirected to the job detail view. A real-time status bar shows the processing progress.

### Step 2 — File parsing

Schema Weaver automatically detects the file type and chooses the best parsing strategy:

| File Type | Strategy |
|---|---|
| CSV | Direct pandas parse with delimiter detection |
| Excel | Openpyxl with multi-sheet support |
| Native PDF | pdfplumber / Camelot for layout-aware table extraction |
| Scanned PDF | Tesseract OCR → text reconstruction → table inference |

You will see the parsed data preview in the UI once this step completes.

### Step 3 — AI schema inference

Click **Infer Schema** to trigger LLM analysis. GPT-5 examines a representative sample of your data (using stratified sampling for large files) and returns:

- A suggested name for each column
- The inferred data type (`string`, `number`, `date`, `boolean`)
- A plain-English description of what the column contains
- A confidence score

The inference uses a **reflexion loop**: if the model's output fails Pydantic validation, the error is automatically fed back to the model for self-correction — up to 3 attempts.

### Step 4 — Review and confirm the schema

The inferred schema is displayed as an editable table. You can:

- **Accept** a suggested column name and type
- **Edit** any field inline
- **Remove** columns you don't need

Once satisfied, click **Confirm Schema** to lock it in.

### Step 5 — Semantic column matching

Click **Generate Embeddings** to create vector representations of your confirmed columns. These are stored in the database and can be searched against any previously processed schema.

To match against an existing schema, use the **Match Schema** panel — paste in your target field names and Schema Weaver will return the closest matches ranked by semantic similarity (cosine distance via pgvector).

### Step 6 — Data transformation

*(In development)* Schema Weaver will generate a Python transformation script that maps your source data to the target schema. The script runs inside the Docker sandbox:

- Network access is disabled
- Memory is capped at the configured limit
- Execution timeout is enforced
- All imports are validated against a whitelist before execution

If the script fails, the traceback is sent back to GPT-5 for automated debugging and repair.

### Step 7 — Export

*(In development)* Download the transformed, normalized dataset as CSV or push it directly to your target database.

---

## API Reference

The full interactive API documentation is available at `http://localhost:8000/docs` when the backend is running.

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/upload` | Upload a file and create a new job |
| `GET` | `/api/v1/jobs` | List all recent jobs |
| `GET` | `/api/v1/jobs/{job_id}` | Get full job details |
| `DELETE` | `/api/v1/jobs/{job_id}` | Delete a job and its associated file |
| `GET` | `/api/v1/jobs/{job_id}/status/stream` | SSE stream for real-time status updates |
| `POST` | `/api/v1/jobs/{job_id}/infer` | Trigger LLM schema inference |
| `POST` | `/api/v1/jobs/{job_id}/schema/select` | Confirm the selected schema |
| `POST` | `/api/v1/jobs/{job_id}/schema/embeddings` | Generate vector embeddings for columns |
| `POST` | `/api/v1/schema/match` | Search for semantically similar schemas |
| `GET` | `/` | Health check |

---

## Project Structure

```
schema-weaver/
├── backend/
│   ├── app/
│   │   ├── api/routes/       # FastAPI route handlers
│   │   ├── core/             # Config and LLM client
│   │   ├── llm/              # Schema inference and embeddings
│   │   ├── parsers/          # PDF, Excel, CSV parsers
│   │   ├── sandbox/          # Docker session manager
│   │   ├── security/         # AST analyzer and audit logging
│   │   ├── tasks/            # Background task handlers
│   │   ├── db.py             # Database connection
│   │   ├── db_models.py      # SQLAlchemy models
│   │   ├── job_store.py      # Job persistence layer
│   │   ├── main.py           # FastAPI app entry point
│   │   └── worker_queue.py   # Async task queue
│   └── sandbox/
│       └── Dockerfile        # Sandbox container image
├── frontend/
│   └── src/
│       ├── App.tsx           # Main React component
│       └── main.tsx          # Entry point
├── alembic/                  # Database migrations
├── .env.example              # Environment variable template
├── requirements.txt          # Python dependencies
└── README.md
```

---

## Roadmap

- [x] File upload and job lifecycle management
- [x] Multi-format parsing (PDF, Excel, CSV) with OCR
- [x] LLM schema inference with reflexion loop
- [x] pgvector semantic column matching
- [x] Docker sandbox for secure code execution
- [x] Real-time SSE status streaming
- [x] React frontend with live job status
- [ ] Visual schema mapper (React Flow node editor)
- [ ] AI-generated transformation scripts + sandbox execution
- [ ] Gamification UI (progress bars, achievements, step completion)
- [ ] Email ingestion (IMAP / MAPI)
- [ ] User authentication and multi-tenancy
- [ ] Export to CSV / database push
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
Built with FastAPI · React · Azure OpenAI · pgvector
</div>
