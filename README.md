# 🤖 AI Code Agent

A **working, demo-ready, research-inspired autonomous coding agent** that edits code, understands repositories, uses tools, iterates with feedback, and shows clear reasoning steps.

Built by combining ideas from four leading AI coding systems:

| System | Concept Used | Where |
|--------|-------------|-------|
| **SWE-agent** | THINK → ACT → OBSERVE → REFLECT loop | `phase2/agent.py` |
| **OpenDevin** | Autonomous task planning & step execution | `phase2/planner.py` |
| **OpenHands** | Structured tool-based interaction | `phase2/tools.py` |
| **Aider** | Context-aware editing, repo maps, diffs | `phase2/selector.py`, `phase1/editor.py` |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI CODE AGENT                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  PHASE 1 — Direct Editor                                       │
│  ┌──────────┐    ┌─────┐    ┌──────────────┐                   │
│  │Instruction│───▶│ LLM │───▶│ Updated Code │                   │
│  │  + Code   │    └─────┘    │   + Diff     │                   │
│  └──────────┘                └──────────────┘                   │
│                                                                 │
│  PHASE 2 — Autonomous Agent                                    │
│  ┌──────┐   ┌──────────┐   ┌─────────┐   ┌──────────────────┐ │
│  │ Task │──▶│ Planner  │──▶│Analyzer │──▶│ Context Selector │ │
│  └──────┘   │(OpenDevin)│   │(Repo Map)│   │    (Aider)       │ │
│             └──────────┘   └─────────┘   └────────┬─────────┘ │
│                                                    │           │
│                              ┌─────────────────────▼─────────┐ │
│                              │    SWE-agent Loop              │ │
│                              │  ┌───────┐                    │ │
│                              │  │ THINK │◀──────────────┐    │ │
│                              │  └───┬───┘               │    │ │
│                              │      ▼                   │    │ │
│                              │  ┌───────┐          ┌────┴──┐│ │
│                              │  │  ACT  │─────────▶│REFLECT││ │
│                              │  │(Tools)│          └───────┘│ │
│                              │  └───┬───┘                   │ │
│                              │      ▼                       │ │
│                              │  ┌─────────┐                 │ │
│                              │  │OBSERVE  │─────────────────┘ │
│                              │  └─────────┘                   │ │
│                              └────────────────────────────────┘ │
│                                                                 │
│  TOOLS (OpenHands-style)                                       │
│  ┌──────────┬───────────┬──────────────┬──────────┐            │
│  │read_file │write_file │search_files  │ run_code │            │
│  └──────────┴───────────┴──────────────┴──────────┘            │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📁 Project Structure

```
ai-code-agent/
├── main.py                 # Entry point — CLI + interactive menu
├── config.py               # Central configuration
├── requirements.txt        # Minimal dependencies
├── README.md
│
├── phase1/                 # Direct code editing (no agent loop)
│   ├── editor.py           # Edit pipeline + diff display
│   └── prompts.py          # Prompt templates
│
├── phase2/                 # Autonomous repo agent
│   ├── agent.py            # SWE-agent loop (core)
│   ├── planner.py          # OpenDevin-style task planner
│   ├── analyzer.py         # Repo structure + AST analysis
│   ├── selector.py         # Aider-style context selection
│   └── tools.py            # OpenHands-style tool registry
│
├── utils/                  # Shared utilities
│   ├── llm.py              # Ollama LLM interface
│   ├── file_ops.py         # File read/write/search
│   ├── executor.py         # Multi-language code execution
│   └── logger.py           # Color-coded structured logging
│
└── demo_repo/              # Demo files for testing
    ├── calculator.py       # Python — buggy add() function
    ├── string_utils.py     # Python — missing features (TODOs)
    ├── index.html          # HTML — basic portfolio page
    ├── style.css           # CSS — needs modernization
    ├── fibonacci.c          # C — off-by-one bug
    ├── HelloWorld.java     # Java — working example
    └── sorting.js          # JavaScript — sorting algorithms
```

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.8+**
- **Ollama** installed and running ([https://ollama.ai](https://ollama.ai))

### Setup

```bash
# 1. Navigate to the project
cd ai-code-agent

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start Ollama (in another terminal)
ollama serve

# 5. Pull a model
ollama pull codellama
# OR
ollama pull mistral
```

### Run

```bash
# Interactive menu (recommended for first run)
python main.py

# Run all demos
python main.py demo

# Direct Phase 1 edit
python main.py phase1 demo_repo/style.css "Make it dark theme with modern gradients"

# Phase 2 autonomous agent
python main.py phase2 demo_repo "Fix the bug in calculator.py where add returns a-b instead of a+b"
```

---

## 🧪 Demo Scenarios

### Demo 1: Phase 1 — CSS Improvement
Modernizes a basic CSS file with dark theme, gradients, and animations.
```bash
python main.py   # Select option [1]
```

### Demo 2: Phase 1 — Python Code Edit
Adds type hints, docstrings, and error handling to a simple Python function.
```bash
python main.py   # Select option [2]
```

### Demo 3: Phase 2 — Bug Fix (Calculator)
The autonomous agent finds and fixes `return a - b` → `return a + b` in `calculator.py`.
```bash
python main.py   # Select option [3]
```

### Demo 4: Phase 2 — Generate Flask App
Creates a complete Flask application from scratch with routes, templates, and error handling.
```bash
python main.py   # Select option [4]
```

### Demo 5: Phase 2 — Add Missing Features
Implements `is_palindrome()` and `remove_duplicates()` functions from TODO comments.
```bash
python main.py   # Select option [5]
```

---

## 🧠 How Each System's Concepts Are Used

### SWE-agent → `phase2/agent.py`
The core execution loop follows SWE-agent's paradigm:
```
for each step:
    THINK  → LLM reasons about the current state
    ACT    → LLM selects and invokes a tool
    OBSERVE → Tool output is captured
    REFLECT → LLM analyzes results, decides if done or needs more steps
```
The agent maintains a rolling history window and uses error feedback to self-correct.

### OpenDevin → `phase2/planner.py`
Before entering the agent loop, the system:
1. Takes a high-level task description
2. Uses the LLM to decompose it into 3–7 sequential steps
3. Each step has an action type (`read`, `edit`, `create`, `run`, `search`)
4. The plan guides the agent's reasoning in each loop iteration

### OpenHands → `phase2/tools.py`
Tools are defined as structured objects with:
- Name, description, parameter schema
- A central `execute_tool()` dispatcher
- The agent must specify tools by name in its JSON output
- Available tools: `read_file`, `write_file`, `create_file`, `search_files`, `run_code`, `list_directory`

### Aider → `phase2/selector.py` + `phase1/editor.py`
- **Repo Map**: AST-based analysis builds a codebase map (functions, classes, imports)
- **Context Selection**: Two-stage ranking (heuristic + LLM) selects the most relevant files
- **Diff Display**: All code changes are shown as colored unified diffs
- **Multi-file Context**: The editor can handle edits across multiple related files

---

## ⚙️ Configuration

All settings are in `config.py` and overridable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_MODEL` | `codellama` | Ollama model to use |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_TIMEOUT` | `120` | Request timeout in seconds |
| `MAX_AGENT_STEPS` | `10` | Max iterations in agent loop |
| `LLM_TEMPERATURE` | `0.1` | LLM temperature (lower = more deterministic) |
| `LLM_NUM_CTX` | `4096` | Context window size |

Example:
```bash
OLLAMA_MODEL=mistral MAX_AGENT_STEPS=15 python main.py demo
```

---

## 📝 Logging

The agent produces structured, color-coded logs:

```
[12:34:56] [SYSTEM]  ⚙️  Ollama connected — model: codellama
[12:34:57] [PLAN]    📋  Step 1 [read] → calculator.py: Read the file
[12:34:58] [THOUGHT] 🧠  The add function uses subtraction. I need to fix it.
[12:34:59] [ACTION]  ⚡  Tool: write_file
[12:35:00] [DIFF]    📝  Changes for calculator.py:
                         - return a - b
                         + return a + b
[12:35:01] [OBSERVATION] 👁️  Successfully wrote to calculator.py
[12:35:02] [RESULT]  ✅  Bug fixed — add(2, 3) now returns 5
```

---

## 🔬 Technical Details

### LLM Communication
- Uses Ollama's HTTP API (`/api/generate`) directly via `requests`
- Robust JSON extraction handles markdown fences, partial output, and malformed responses
- Balanced bracket matching for reliable JSON parsing from noisy LLM output

### Multi-Language Support
The executor (`utils/executor.py`) supports:
- **Python** → `python3`
- **JavaScript** → `node`
- **Java** → `javac` + `java` (compile & run)
- **C** → `gcc` (compile & run)
- **C++** → `g++` (compile & run)
- **Ruby** → `ruby`
- **Shell** → `bash`

### AST Analysis
Python files are deeply analyzed using the `ast` module to extract:
- Function definitions (name, arguments, line numbers)
- Class definitions (name, methods)
- Import statements

This powers the context selector's understanding of code structure.

---

## 🚫 Non-Goals (By Design)

- **No LangChain** — Direct Ollama HTTP calls for simplicity
- **No paid APIs** — Runs 100% locally with Ollama
- **No heavy frameworks** — Pure Python with minimal dependencies
- **Not production-grade** — Research demo, not a production tool

---

## 📄 License

MIT — Use freely for research, learning, and experimentation.
