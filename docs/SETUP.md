# Setup & Installation

## Prerequisites

- **Python 3.12** — must be exactly 3.12 (3.13+ may lack pre-built wheels for some dependencies and will fall back to slow source builds)
- **HuggingFace API token** — required for embeddings, LLM, and reranking

---

## Installation

```bash
git clone <repo-url>
cd doc-search

# Create virtual environment with Python 3.12
#   Windows (use py launcher to select 3.12 explicitly):
py -3.12 -m venv .venv
#   Linux/macOS (if python3.12 is available):
python3.12 -m venv .venv

# Activate
#   Windows CMD:
.venv\Scripts\activate.bat
#   Windows PowerShell:
.venv\Scripts\Activate.ps1
#   Linux/macOS / Git Bash:
source .venv/bin/activate

# Verify — should show Python 3.12.x
python --version

# Install
pip install -e .

# Dev dependencies (pytest, httpx, ruff, openapi-python-client)
pip install -e ".[dev]"
```

---

## Configuration

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
# Edit .env — at minimum set HF_TOKEN
```

### All Variables

See `.env.example` for a complete annotated list. At minimum:

| Variable | Required | Description |
|----------|----------|-------------|
| `HF_TOKEN` | Yes | HuggingFace API token |
| `INTELLIGENT_SEARCH_MODEL` | No | LLM model (default: `deepseek-ai/DeepSeek-V3.2-Exp`) |
| `EMBEDDING_MODEL_URL` | No | Embedding model (default: `Qwen/Qwen3-Embedding-8B`) |
| `RERANKER_MODEL` | No | Reranker model (default: `mixedbread-ai/mxbai-rerank-large-v1`) |
| `DOCSEARCH_TRANSPORT` | No | MCP transport: `stdio` (default) or `http` |
| `DOCSEARCH_HOST` | No | MCP HTTP host (default: `127.0.0.1`) |
| `DOCSEARCH_PORT` | No | MCP HTTP port (default: `8002`) |
| `API_HOST` | No | REST API host (default: `0.0.0.0`) |
| `API_PORT` | No | REST API port (default: `8001`) |
| `API_RELOAD` | No | Hot reload: `true` or `false` (default: `false`) |
```

### Getting a HuggingFace Token

1. [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Create a "Read access" token
3. Must have access to: `Qwen/Qwen3-Embedding-8B`, `deepseek-ai/DeepSeek-V3.2-Exp`, `mixedbread-ai/mxbai-rerank-large-v1`

---

## Running

### REST API

```bash
python -m doc_search.presentation.api
# → http://localhost:8001
# → Swagger: http://localhost:8001/docs
# → ReDoc: http://localhost:8001/redoc
```

### MCP Server

```bash
# Stdio (Claude Desktop, Cursor)
python -m doc_search.presentation.mcp

# HTTP
DOCSEARCH_TRANSPORT=http DOCSEARCH_PORT=8002 python -m doc_search.presentation.mcp
```

### Claude Desktop Config

```json
{
  "mcpServers": {
    "doc-search": {
      "command": "python",
      "args": ["-m", "doc_search.presentation.mcp"],
      "cwd": "/path/to/doc-search"
    }
  }
}
```

---

## Docker

```bash
# REST API
docker compose up doc-search-api

# MCP (stdio)
docker compose up doc-search-mcp
```

Both containers mount `.env` as read-only volume.

---

## Quick Verification

```bash
# Health check
curl http://localhost:8001/health

# Create an account
curl -X POST http://localhost:8001/accounts/ \
  -H "Content-Type: application/json" \
  -d '{"name": "my-docs"}'

# Create a collection
curl -X POST http://localhost:8001/collections/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Knowledge Base", "account_id": "<account_id>"}'

# Upload a markdown file
curl -X POST "http://localhost:8001/documents/upload?collection_id=<collection_id>" \
  -F "file=@document.md"

# Check progress
curl http://localhost:8001/documents/progress/<job_id>

# Search
curl -X POST "http://localhost:8001/search/<job_id>?query=my+search+terms"

# Intelligent search
curl -X POST "http://localhost:8001/intelligent_search/<job_id>?query=Explain+how+to+X"
```

---

## Data Storage

```
data/
├── documents.db              # SQLite (all tables)
├── indexes/                  # FAISS + BM25 indexes
│   └── {account_id}/{collection_id}/
├── logos/                    # Collection logos
└── logs/                     # App logs
```

---

## Troubleshooting

### FAISS won't install
```bash
# Ubuntu/Debian
sudo apt-get install build-essential

# macOS
xcode-select --install

# Windows — install Visual Studio Build Tools with C++ workload
```

### "HF_TOKEN not set"
The `.env` file must be in the project root. The app calls `load_dotenv()` on startup. Verify with `echo $HF_TOKEN`.

### "No search indexes available"
Document hasn't finished processing. Check `GET /documents/progress/{job_id}` and wait for `status: completed`.

### MCP server won't connect
For stdio in Claude Desktop, ensure:
- `cwd` points to the project root (where `.env` lives)
- Python path is correct
- No other process holds the stdio pipes

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest                          # All tests
pytest tests/test_mcp/          # MCP-specific
pytest -v                       # Verbose
```
