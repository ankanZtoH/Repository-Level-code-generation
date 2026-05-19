<p align="center">
  <h1 align="center">🤖 AuraCode — Autonomous AI Code Agent</h1>
  <p align="center">
    A research-inspired, fully local, autonomous coding agent that analyzes repositories,<br>
    plans fixes, edits code across multiple files, and self-corrects — all powered by Ollama.
  </p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python" alt="Python">
  <img src="https://img.shields.io/badge/LLM-Ollama%20(local)-green?logo=llama" alt="Ollama">
  <img src="https://img.shields.io/badge/framework-FastAPI-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License">
  <img src="https://img.shields.io/badge/status-research%20demo-orange" alt="Status">
</p>

---

## 📖 Overview

**AuraCode** is a working, demo-ready autonomous coding agent built entirely in Python. It runs **100% locally** using [Ollama](https://ollama.ai) — no paid API keys, no cloud services, no LangChain.

The agent can:
- **Fix bugs** across multi-file repositories by tracing errors through dependency graphs
- **Create new projects** from natural language descriptions
- **Implement missing features** from TODO comments
- **Self-correct** by running code, analyzing errors, and iterating on fixes

It combines ideas from four leading AI coding research systems:

| Research System | Concept Adopted | Implementation |
|-----------------|----------------|----------------|
| **SWE-agent** | THINK → ACT → OBSERVE → REFLECT loop | `phase2/agent.py`, `phase2/swe_loop.py` |
| **OpenDevin** | Autonomous task planning & step execution | `phase2/planner.py` |
| **OpenHands** | Structured tool-based interaction | `phase2/tools.py` |
| **Aider** | Context-aware editing, repo maps, diffs | `phase2/selector.py`, `phase1/editor.py` |

---

## ✨ Features

- **Two operating modes** — Phase 1 (direct code editing) and Phase 2 (autonomous agent loop)
- **Multi-language support** — Python, JavaScript, C, C++, Java, Ruby, Shell, HTML, CSS
- **Dependency graph analysis** — AST-based import tracing and cross-file call graph construction
- **Semantic code retrieval** — Embedding-based search using `sentence-transformers` (with TF-IDF fallback)
- **Web IDE interface** — Three-panel IDE (file explorer, code editor, agent chat) via FastAPI
- **Real-time streaming** — Server-Sent Events (SSE) for live agent step visualization
- **Diff tracking** — Colored unified diffs for every code change
- **Loop protection** — Prevents infinite loops, detects stuck behavior, enforces step limits
- **Pre-write validation** — Syntax checking (Python `compile()`, bracket matching for JS/C/Java, JSON/HTML validation)
- **Safe partial edits** — Aider-style `SEARCH/REPLACE` blocks with fuzzy matching
- **Structured error analysis** — Pattern-based error classification with actionable fix suggestions
- **Placeholder guard** — Detects when LLM returns template text instead of real code

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         AURACODE AGENT                           │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  PHASE 1 — Direct Editor (no agent loop)                        │
│  ┌────────────┐    ┌─────┐    ┌───────────────┐                 │
│  │ Instruction │───▶│ LLM │───▶│ Updated Code  │                 │
│  │  + Code     │    └─────┘    │   + Diff      │                 │
│  └────────────┘                └───────────────┘                 │
│                                                                  │
│  PHASE 2 — Autonomous Agent                                     │
│  ┌──────┐   ┌──────────┐   ┌──────────┐   ┌─────────────────┐  │
│  │ Task │──▶│ Planner  │──▶│ Analyzer │──▶│Context Selector │  │
│  └──────┘   │(OpenDevin)│   │(Repo Map)│   │   (Aider)       │  │
│             └──────────┘   └──────────┘   └───────┬─────────┘  │
│                                                    │             │
│                              ┌─────────────────────▼──────────┐ │
│                              │    SWE-agent Loop               │ │
│                              │  ┌───────┐                     │ │
│                              │  │ THINK │◀─────────────┐      │ │
│                              │  └───┬───┘              │      │ │
│                              │      ▼                  │      │ │
│                              │  ┌───────┐         ┌────┴───┐ │ │
│                              │  │  ACT  │────────▶│REFLECT │ │ │
│                              │  │(Tools)│         └────────┘ │ │
│                              │  └───┬───┘                    │ │
│                              │      ▼                        │ │
│                              │  ┌─────────┐                  │ │
│                              │  │OBSERVE  │──────────────────┘ │
│                              │  └─────────┘                    │
│                              └─────────────────────────────────┘│
│                                                                  │
│  TOOLS (OpenHands-style)                                        │
│  ┌──────────┬───────────┬──────────┬──────────┬──────────────┐  │
│  │read_file │write_file │run_code  │run_tests │search_files  │  │
│  └──────────┴───────────┴──────────┴──────────┴──────────────┘  │
│                                                                  │
│  WEB UI (FastAPI + SSE)                                         │
│  ┌──────────────┬──────────────┬──────────────────────────────┐ │
│  │ File Explorer│ Code Editor  │ Agent Chat (live streaming)  │ │
│  └──────────────┴──────────────┴──────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
ai-code-agent/
├── server.py                # FastAPI server — Web UI entry point (start here)
├── config.py                # Central configuration (model, timeouts, limits)
├── check_health.py          # Full project health check script
├── requirements.txt         # Python dependencies
├── README.md
├── TESTING_GUIDE.md         # Detailed testing & verification guide
│
├── phase1/                  # Direct code editing (no agent loop)
│   ├── editor.py            # Edit pipeline: instruction + code → LLM → updated code + diff
│   └── prompts.py           # Prompt templates for Phase 1
│
├── phase2/                  # Autonomous agent system
│   ├── agent.py             # Core agent loop — FIX mode, CREATE mode, loop protection
│   ├── swe_loop.py          # SWE-agent conversational loop (multi-turn chat)
│   ├── planner.py           # OpenDevin-style task decomposition (3–7 steps)
│   ├── analyzer.py          # Repo analysis: AST parsing, dependency graph, code tree
│   ├── selector.py          # Aider-style context selection (heuristic + retrieval ranking)
│   ├── retrieval.py         # Semantic code retrieval (sentence-transformers / TF-IDF fallback)
│   └── tools.py             # Tool registry & execution dispatcher
│
├── utils/                   # Shared utilities
│   ├── llm.py               # Ollama HTTP API interface (generate + chat endpoints)
│   ├── executor.py          # Multi-language code execution (compile & run)
│   ├── file_ops.py          # Safe file read/write/search with cache invalidation
│   ├── validator.py         # Pre-write syntax validation (Python, JS, C, JSON, HTML)
│   ├── safe_edit.py         # Aider-style SEARCH/REPLACE partial editing
│   ├── error_handler.py     # Error classification & fix suggestion engine
│   └── logger.py            # Color-coded structured logging with timestamps
│
├── frontend/                # Web IDE interface
│   ├── index.html           # Three-panel layout (files, editor, agent chat)
│   ├── style.css            # Dark-theme IDE styling
│   └── app.js               # Frontend logic (SSE streaming, file tree, editor)
│
├── demo_repo/               # Demo repository with intentional bugs for testing
│   ├── main.py              # Entry point — imports calculator, string_utils, formatter
│   ├── calculator.py        # Has deliberate bug: add() returns a - b instead of a + b
│   ├── string_utils.py      # Has TODO stubs: is_palindrome(), remove_duplicates()
│   ├── formatter.py         # Result formatting utilities
│   └── tests/
│       └── test_calculator.py
│
├── tests/                   # Project regression tests
│   ├── test_validation_and_graph.py  # Dependency graph, validation, cache tests
│   ├── test_scenarios.py             # Agent scenario tests
│   └── test_app.py                   # Application tests
│
└── test_output/             # Agent-generated output directory
```

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| **Language** | Python 3.10+ |
| **LLM Runtime** | [Ollama](https://ollama.ai) (local) |
| **Default Model** | CodeLlama (via Ollama) |
| **Web Framework** | FastAPI + Uvicorn |
| **LLM Communication** | Direct HTTP via `requests` (no LangChain) |
| **Code Analysis** | Python `ast` module for AST parsing |
| **Semantic Search** | `sentence-transformers` (optional, TF-IDF fallback) |
| **Frontend** | Vanilla HTML/CSS/JS (no build step) |
| **Testing** | `unittest` / `pytest` |

---

## 🚀 Setup & Installation

### Prerequisites

| Requirement | Details |
|-------------|---------|
| **Python** | 3.10 or higher |
| **Ollama** | Installed and running — [download here](https://ollama.ai) |
| **Git** | For cloning the repository |
| **GCC/G++** | *(Optional)* Required only if you want the agent to compile C/C++ files |
| **Java JDK** | *(Optional)* Required only if you want the agent to compile Java files |
| **Node.js** | *(Optional)* Required only if you want the agent to execute JavaScript files |

### Step 1 — Clone the Repository

```bash
git clone https://github.com/ankanZtoH/Repository-Level-code-generation.git
cd Repository-Level-code-generation
```

### Step 2 — Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate          # Windows
```

### Step 3 — Install Python Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

> **Note:** `sentence-transformers` (~80 MB model download on first run) is optional. The agent works without it using a TF-IDF fallback. If you want to skip it:
> ```bash
> pip install requests fastapi uvicorn pydantic pytest
> ```

### Step 4 — Install & Start Ollama

```bash
# Install Ollama (if not already installed)
# macOS:  Download from https://ollama.ai
# Linux:  curl -fsSL https://ollama.ai/install.sh | sh

# Start the Ollama server
ollama serve
```

### Step 5 — Pull a Model

In a **separate terminal**:

```bash
ollama pull codellama
```

Other compatible models:

```bash
ollama pull mistral
ollama pull deepseek-coder
ollama pull codellama:13b
ollama pull llama3
```

### Step 6 — Verify Installation

```bash
source venv/bin/activate
python check_health.py
```

Expected output — all checks should pass:

```
=======================================================
  AuraCode Health Check
=======================================================

📦 Imports
  ✅  Core imports: All modules import OK

🔍 Validators
  ✅  Python validator: Valid=OK, Invalid=caught (...)
  ✅  JSON validator: JSON validation working
  ✅  Bracket validator: Bracket matching working

  ... (more checks) ...

=======================================================
  Results: 14/14 checks passed ✅
=======================================================
```

---

## ▶️ Running the Project

### Web UI (Recommended)

Start the FastAPI server:

```bash
python server.py
```

Then open your browser at:

```
http://localhost:8000
```

The web IDE provides:
- **Left panel** — File explorer (load any project directory)
- **Center panel** — Code editor with line numbers
- **Right panel** — Agent chat with real-time streaming output

**Using the Web UI:**

1. Enter a project path in the top bar (default: `demo_repo`) and click **Load**
2. Browse files in the left panel, click to view/edit in the center
3. Type a task in the agent chat (right panel), e.g.:
   - `Fix the bug in calculator.py where add returns a-b instead of a+b`
   - `Implement the is_palindrome function in string_utils.py`
4. Click **▶ Run** — watch the agent work in real-time via SSE streaming

### Alternative: Uvicorn with Auto-Reload (Development)

```bash
uvicorn server:app --reload --port 8000
```

### Programmatic Usage (Python API)

You can also use the agent directly from Python:

```python
from phase2.agent import run_agent

# Fix a bug in a repository
result = run_agent(
    task="Fix calculator.py so add(2, 3) returns 5",
    repo_path="./demo_repo"
)
print(result)
# {"success": True, "summary": "Fixed calculator.py", "steps": 5}
```

```python
# Use the SWE-agent conversational loop
from phase2.swe_loop import run_swe_agent

result = run_swe_agent(
    task="Implement the is_palindrome function in string_utils.py",
    repo_path="./demo_repo",
    max_steps=15
)
```

```python
# Phase 1: Direct code editing (no agent loop)
from phase1.editor import edit_file

edit_file(
    instruction="Add type hints and docstrings to all functions",
    filepath="./demo_repo/calculator.py"
)
```

---

## 🧪 Example Tasks

Here are tasks you can try with the `demo_repo/`:

| Task Description | What the Agent Does |
|-----------------|-------------------|
| `Fix the bug in calculator.py where add returns wrong result` | Traces the bug (`return a - b` → `return a + b`), writes fix, verifies |
| `Implement is_palindrome and remove_duplicates in string_utils.py` | Reads TODO stubs, generates implementations, runs tests |
| `Create a Flask web application with routes for home and about pages` | Generates multi-file Flask app from scratch |
| `Fix all bugs in the repository` | Runs broad fix-all mode: analyzes every file via dependency BFS |
| `Add error handling to the divide function in calculator.py` | Reads file, adds try/except, verifies behavior |

---

## 🧠 How the Agent Works Internally

### Phase 1 — Direct Editor

A simple pipeline with no agent loop:

```
Instruction + Code → LLM Prompt → Ollama → Updated Code → Diff Display
```

Used for one-shot edits like adding docstrings, reformatting, or applying a specific change.

### Phase 2 — Autonomous Agent

The full autonomous pipeline:

```
1. ANALYZE    → Scan repository, build AST analysis, dependency graph, code tree
2. INDEX      → Create semantic index (embeddings or TF-IDF) for retrieval
3. PLAN       → LLM decomposes task into 3–7 sequential steps (OpenDevin-style)
4. CLASSIFY   → Auto-detect mode: FIX (debug existing code) or CREATE (new files)
5. EXECUTE    → Enter the SWE-agent loop:
                 ┌─ THINK:   LLM reasons about current state
                 ├─ ACT:     LLM selects a tool (read_file, write_file, run_code, etc.)
                 ├─ OBSERVE: Tool output is captured and analyzed
                 └─ REFLECT: LLM decides if done or needs more steps
6. VALIDATE   → Run code + run repository tests to verify the fix
7. SELF-CORRECT → If errors remain, analyze error type, retry with feedback
```

### Key Internal Components

| Component | File | Role |
|-----------|------|------|
| **Agent Loop** | `phase2/agent.py` | FIX mode (queue-based multi-file traversal), CREATE mode, self-correction |
| **SWE Loop** | `phase2/swe_loop.py` | Multi-turn conversational loop with message history |
| **Planner** | `phase2/planner.py` | Breaks tasks into atomic steps with expected outcomes |
| **Analyzer** | `phase2/analyzer.py` | AST parsing, dependency graph, call graph, file importance ranking |
| **Selector** | `phase2/selector.py` | Ranks files by relevance using heuristics + retrieval scores |
| **Retrieval** | `phase2/retrieval.py` | Semantic search over code chunks (embeddings or TF-IDF) |
| **Tools** | `phase2/tools.py` | Tool registry with 6 tools: `read_file`, `write_file`, `patch_file`, `run_code`, `run_tests`, `search_files` |
| **LLM Interface** | `utils/llm.py` | Ollama HTTP API with JSON extraction and balanced bracket parsing |
| **Executor** | `utils/executor.py` | Runs code in subprocess; compiles C/C++/Java before execution |
| **Validator** | `utils/validator.py` | Pre-write syntax checking to prevent broken writes |
| **Safe Edit** | `utils/safe_edit.py` | Aider-style SEARCH/REPLACE with fuzzy matching |
| **Error Handler** | `utils/error_handler.py` | Classifies 12 error types with actionable suggestions |
| **Loop Protector** | `phase2/agent.py` | Prevents infinite loops, detects stuck agents, suggests recovery |

### Agent Modes

The agent uses explicit mode separation for role-specific behavior:

| Mode | When Active | Behavior |
|------|-------------|----------|
| `PLANNING` | Task decomposition phase | Focus on breaking task into steps, no code changes |
| `EXECUTING` | Normal operation | Follow the plan, make precise code changes |
| `DEBUGGING` | After errors detected | Analyze errors, trace root cause, generate targeted fix |
| `CREATING` | New file generation | Generate complete, working code files from scratch |

---

## ⚙️ Configuration

All settings are centralized in [`config.py`](config.py) and can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `codellama` | Ollama model to use |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_TIMEOUT` | `120` | Request timeout in seconds |
| `MAX_AGENT_STEPS` | `20` | Maximum iterations in the agent loop |
| `MAX_RETRIES` | `7` | Maximum retries for a single file fix |
| `LLM_TEMPERATURE` | `0.1` | LLM temperature (lower = more deterministic) |
| `LLM_NUM_CTX` | `8192` | Context window size (tokens) |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_FILE` | `agent.log` | Log file path |

**Override via environment:**

```bash
OLLAMA_MODEL=mistral MAX_AGENT_STEPS=25 python server.py
```

---

## 🔄 Changing the LLM Model

### Where to Change

The model is configured in **one place**:

**File:** [`config.py`](config.py) — **Line 10**

```python
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama")  # ← Change this default
```

### Option 1: Change the Default in `config.py`

Edit line 10 of `config.py`:

```python
# Before (default)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama")

# Example replacements:
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "deepseek-coder")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama:13b")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5-coder")
```

### Option 2: Use an Environment Variable (No Code Changes)

```bash
# Set for a single run
OLLAMA_MODEL=mistral python server.py

# Or export for the session
export OLLAMA_MODEL=deepseek-coder
python server.py
```

### Option 3: Switch Models at Runtime via the Web UI

The web UI has a **model dropdown** in the top bar. You can also switch models via the API:

```bash
curl -X POST http://localhost:8000/api/set_model \
  -H "Content-Type: application/json" \
  -d '{"model": "mistral"}'
```

### Model Compatibility Notes

| Model | Size | JSON Reliability | Code Quality | Notes |
|-------|------|-----------------|-------------|-------|
| `codellama` | 7B | ⭐⭐⭐ | ⭐⭐⭐⭐ | Default. Best balance for code tasks |
| `codellama:13b` | 13B | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Better quality, needs more RAM (~8 GB) |
| `mistral` | 7B | ⭐⭐⭐⭐ | ⭐⭐⭐ | Good general reasoning, decent at code |
| `deepseek-coder` | 6.7B | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | Strong code model, good JSON output |
| `llama3` | 8B | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | Best instruction following, average at code |
| `qwen2.5-coder` | 7B | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Excellent code quality |

> **Important:** After changing the model, make sure to pull it first:
> ```bash
> ollama pull <model-name>
> ```

> **Context window:** If using a model with a smaller context window, reduce `LLM_NUM_CTX` in `config.py` accordingly. The default `8192` works for most 7B models.

---

## 📝 Logging

The agent produces structured, color-coded terminal output:

```
[12:34:56] [SYSTEM]  ⚙️  Querying LLM (codellama)...
[12:34:57] [PLAN]    📋  Step 1 [read] → calculator.py: Read the file
[12:34:58] [THOUGHT] 🧠  The add function uses subtraction. I need to fix it.
[12:34:59] [ACTION]  ⚡  Step 3: write_file calculator.py
[12:35:00] [DIFF]    📝  Changes for calculator.py:
                         - return a - b
                         + return a + b
[12:35:01] [OBSERVATION] 👁️  Written: calculator.py
[12:35:02] [RESULT]  ✅  Done: Fixed calculator.py
```

---

## 🔬 Technical Details

### LLM Communication

- Uses Ollama's REST API directly via `requests` (`/api/generate` for single-shot, `/api/chat` for multi-turn)
- Robust JSON extraction handles markdown fences, partial output, and malformed responses
- Balanced bracket matching for reliable JSON parsing from noisy LLM output
- Automatic JSON retry: if the LLM returns invalid JSON, a correction prompt is sent

### Multi-Language Code Execution

| Language | Runtime | Method |
|----------|---------|--------|
| Python | `python3` | Direct execution |
| JavaScript | `node` | Direct execution |
| Ruby | `ruby` | Direct execution |
| Shell | `bash` | Direct execution |
| C | `gcc` | Compile → run → cleanup |
| C++ | `g++` | Compile → run → cleanup |
| Java | `javac` + `java` | Compile → run → cleanup |
| HTML/CSS | — | Non-executable (write-only, validated) |

### Test Detection

The agent auto-detects and runs repository tests:

| Ecosystem | Detection | Command |
|-----------|-----------|---------|
| Python (pytest) | `pytest.ini`, `test_*.py` files | `python -m pytest -q` |
| Python (unittest) | `test_*.py` files | `python -m unittest discover` |
| JavaScript | `package.json` with test script | `npm test` |
| Go | `go.mod` | `go test ./...` |
| Rust | `Cargo.toml` | `cargo test` |

### Repository Analysis

Python files are deeply analyzed using the `ast` module:
- **Functions** — name, arguments, line numbers, call graph
- **Classes** — name, methods
- **Imports** — module dependencies

Non-Python files get lightweight dependency extraction:
- **JS/TS** — `import`/`require()` statements
- **HTML** — `src`/`href` attributes
- **CSS** — `@import` and `url()` references
- **C/C++** — `#include "..."` directives

---

## 🔧 API Endpoints

The FastAPI server exposes these endpoints:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Serve the web IDE |
| `GET` | `/api/status` | Check Ollama availability and current model |
| `GET` | `/api/models` | List all locally available Ollama models |
| `POST` | `/api/set_model` | Switch the active model at runtime |
| `GET` | `/api/file_tree?path=...` | Get directory tree for the file explorer |
| `GET` | `/api/read_file?path=...` | Read a file's content |
| `POST` | `/api/write_file` | Write content to a file |
| `POST` | `/api/run_task` | Start an agent task (returns SSE stream) |

---

## ❓ Troubleshooting

### Ollama not reachable

```
[ERROR] Cannot connect to Ollama at http://localhost:11434
```

**Fix:** Start the Ollama server in a separate terminal:

```bash
ollama serve
```

### Model not found

```
[ERROR] Model 'codellama' not found
```

**Fix:** Pull the model:

```bash
ollama pull codellama
```

### Import errors

```
ModuleNotFoundError: No module named 'fastapi'
```

**Fix:** Ensure you're in the virtual environment and dependencies are installed:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### LLM returns empty or invalid JSON

This can happen with smaller models. Try:

1. Increase the timeout: `OLLAMA_TIMEOUT=180`
2. Use a more capable model: `OLLAMA_MODEL=codellama:13b`
3. Lower the context window if running out of memory: `LLM_NUM_CTX=4096`

### Agent stuck in a loop

The built-in `LoopProtector` should catch this, but if needed:

- Reduce `MAX_AGENT_STEPS` in `config.py` (default: 20)
- The agent automatically suggests recovery strategies when stuck

### sentence-transformers download fails

The semantic retrieval is **optional**. The agent falls back to TF-IDF automatically. To skip entirely, install only the core dependencies:

```bash
pip install requests fastapi uvicorn pydantic pytest
```

### Port already in use

```bash
# Find and kill the process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use a different port
uvicorn server:app --port 8001
```

---

## 🧪 Running Tests

```bash
# Activate the virtual environment
source venv/bin/activate

# Run regression tests
python -m unittest discover

# Run the full health check
python check_health.py
```

For a comprehensive verification checklist, see [`TESTING_GUIDE.md`](TESTING_GUIDE.md).

---

## 🚫 Design Decisions

- **No LangChain** — Direct Ollama HTTP calls for simplicity and transparency
- **No paid APIs** — Runs 100% locally with Ollama, no API keys required
- **No heavy frameworks** — Pure Python with minimal dependencies
- **Not production-grade** — This is a research demo, not a production tool

---

## 📄 License

MIT — Use freely for research, learning, and experimentation.