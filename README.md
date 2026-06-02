# DocuFlow AI

Centralizes administrative documents (invoices, contracts, medical forms, reports,
IDs/certificates), extracts their key fields with **OCR + a local LLM**, organizes them by
type, and answers natural-language questions **about a single document or across the whole
collection** (with live "thinking").

Everything runs locally: OCR via **docTR**, language model via **Ollama** — no external API
calls, no secrets baked into the images.

## Architecture

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLModel | docTR/Ollama are Python; strict typing |
| OCR | docTR (GPU, CPU fallback) | imposed; word-level geometry → field bboxes |
| LLM | Ollama `qwen2.5:3b` (pipeline) + `qwen3:4b` (QA thinking) | local; fit 6 GB VRAM alongside docTR |
| DB | Postgres (JSONB) | metadata + extracted fields/bboxes/OCR text |
| Queue | `jobs` table + 1 worker (`FOR UPDATE SKIP LOCKED`) | serializes the GPU; durable; no Redis |
| Frontend | React + TS + Vite, CSS variables | design tokens; no heavy UI framework |

The **field schemas live once** in `shared/schemas.json`, consumed by both the backend
(Pydantic validation) and the frontend (typed import). Six types: invoice, contract,
medical, report, id, other.

### Processing pipeline (worker, GPU-serialized)

```
queued → processing → OCR (docTR) → classify type (Ollama) → parse fields (Ollama, strict JSON)
       → validate against schema → derive bbox (match value ↔ docTR words) → duplicate check → done
```

Bounding boxes are **derived server-side** by matching each extracted value against docTR
word geometry (rapidfuzz) — never guessed by the LLM. Duplicate detection compares the
type's *identifying* fields (normalized fuzzy similarity), not embeddings.

### QA — two scopes (no vector store, no embeddings)

- **Single document**: the active doc's OCR text + extracted fields are stuffed into
  `qwen2.5:3b`. The cited snippet is located back in the OCR text → `Found on line N: "…"`.
- **Whole collection**: a compact **structured digest** (per-doc key fields + aggregates,
  reusing the Summary aggregation) is fed to `qwen3:4b`, which **streams its thinking live**
  (NDJSON, time-boxed) before the answer. No raw-OCR stuffing, so it scales to many docs.

PDFs are displayed as a **server-rendered page image** (same raster docTR used), so the
field bounding-box overlay aligns exactly — the browser's native PDF viewer is not used.

## Quick start (Docker)

Requires Docker + the **NVIDIA Container Toolkit** for GPU.

```bash
cp .env.example .env          # adjust if needed; no secrets required
docker compose up --build     # starts db, ollama, backend, worker, frontend
docker compose exec ollama ollama pull qwen2.5:3b   # pipeline model (one-time)
docker compose exec ollama ollama pull qwen3:4b     # collection-QA thinking model (one-time)
```

> On a local GPU machine, use `docker compose -f docker-compose.local.yml up --build` —
> it bind-mounts the host's already-downloaded Ollama models (no re-pull).

- Frontend: http://localhost:5173
- API: http://localhost:8000  (health: `/api/health`)

Upload a document, watch the sidebar move `queued → processing → done`, then inspect the
extracted fields, hover a field to highlight its bbox, ask a question, or open the Summary
tab to export CSV.

### CPU fallback (no GPU)

Set `OCR_DEVICE=cpu` in `.env` and remove the `deploy.resources` GPU blocks for the
`ollama` and `worker` services in `docker-compose.yml`. Everything still works — OCR and
inference are just slower.

## Local development (no Docker)

**Backend** (needs a running Postgres + Ollama):

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DATABASE_URL="postgresql+psycopg://docuflow:docuflow@localhost:5432/docuflow"
export OLLAMA_HOST="http://localhost:11434"
export OCR_DEVICE=cuda            # or cpu

uvicorn app.main:app --reload     # API on :8000
python -m app.worker              # worker, separate terminal
```

Pull the models once: `ollama pull qwen2.5:3b && ollama pull qwen3:4b`.

**Frontend:**

```bash
cd frontend
npm install
npm run dev                       # Vite on :5173, proxies /api → :8000
```

## Configuration

All settings come from environment variables (see `backend/app/config.py` / `.env.example`):

| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | local Postgres | `postgresql+psycopg://…` |
| `OLLAMA_HOST` | `http://localhost:11434` | |
| `OLLAMA_MODEL` | `qwen2.5:3b` | pipeline (classify/parse) + single-doc QA |
| `OLLAMA_QA_MODEL` | `qwen3:4b` | collection QA; reasoning/thinking model |
| `OCR_DEVICE` | `cuda` | `cpu` = degraded fallback |
| `DUPLICATE_THRESHOLD` | `0.85` | similarity cutoff |

### Hardware note

Developed against an **RTX 3060 Laptop (6 GB VRAM)**. docTR (~1.5 GB) + `qwen2.5:3b`
(pipeline) coexist comfortably; the `qwen3:4b` QA model is loaded on demand (`keep_alive`)
and may briefly evict the pipeline model — fine since collection QA is interactive. Larger
(8B) models would force constant load/unload and are not the default.

## Tests

```bash
cd backend && source .venv/bin/activate
pytest
```

Unit tests cover schema validation, bbox derivation, duplicate similarity, CSV export and
citation building. The integration test (`test_pipeline_integration.py`) runs the full
`process_document` orchestration on in-memory SQLite with OCR and Ollama mocked — so the
suite needs **no GPU and no Ollama**. A real-stack end-to-end run is exercised manually via
`docker compose up` (see Quick start).

## Layout

```
shared/schemas.json        # single source of truth for the 6 document types
backend/app/               # FastAPI app, routes, pipeline (ocr/classify/parse/bbox/dup), worker
backend/tests/             # pytest suite
frontend/src/              # React + TS UI (schema-driven)
docker-compose.yml         # portable stack: db + ollama + backend + worker + frontend
docker-compose.local.yml   # local GPU stack (reuses host's Ollama models)
```
