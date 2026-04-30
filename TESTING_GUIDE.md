# Testing Guide

Use this guide to verify that the autonomous coding agent is working after changes.
Run all commands from the repository root:

```bash
cd "/Users/subham/Desktop/ET Project/ai-code-agent"
```

## 1. Prepare The Environment

If the virtual environment already exists:

```bash
source venv/bin/activate
python -m pip install -r requirements.txt
```

If you need to recreate it:

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Ollama must be running for live agent tests:

```bash
ollama serve
ollama pull codellama
```

In another terminal, confirm the model is available:

```bash
ollama list
```

## 2. Fast Health Check

Run Python compile checks. This catches syntax and import-time parsing problems.

```bash
venv/bin/python -m py_compile \
  main.py server.py \
  phase1/editor.py phase1/prompts.py \
  phase2/agent.py phase2/analyzer.py phase2/planner.py \
  phase2/retrieval.py phase2/selector.py phase2/tools.py \
  utils/executor.py utils/file_ops.py utils/error_handler.py \
  tests/test_validation_and_graph.py
```

Expected result: no output and exit code 0.

## 3. Run The Regression Tests

```bash
venv/bin/python -m unittest discover
```

Expected result:

```text
Ran 4 tests

OK
```

These tests check:

- `run_tests` detects Python test suites.
- `run_tests` works through the agent tool dispatcher.
- The repository dependency graph links JS/TS, HTML/CSS, and C/C++ files.
- Python bytecode caches are removed after `.py` rewrites.

## 4. Test The `run_tests` Tool Directly

```bash
venv/bin/python - <<'PY'
from phase2.tools import execute_tool

output = execute_tool({"tool": "run_tests"}, ".")
print(output)
PY
```

Expected result: a `Test command:` line and `Return code: 0`.

## 5. Run A Live End-To-End Agent Test

This creates a temporary repository with a real failing test, then asks the agent
to fix it. It does not modify your main repo.

```bash
tmpdir=$(mktemp -d)

cat > "$tmpdir/calc.py" <<'PY'
def add(a, b):
    return a - b
PY

cat > "$tmpdir/test_calc.py" <<'PY'
import unittest
from calc import add

class CalcTest(unittest.TestCase):
    def test_add(self):
        self.assertEqual(add(2, 3), 5)

if __name__ == "__main__":
    unittest.main()
PY

echo "Temporary repo: $tmpdir"

venv/bin/python main.py phase2 "$tmpdir" \
  "Fix calc.py so the add function passes the existing repository tests. Do not modify tests."
```

Expected agent behavior:

- It analyzes the temporary repo.
- It creates a plan.
- It runs `calc.py`.
- It runs the repository tests and sees the failing assertion.
- It reads `calc.py`.
- It uses semantic context from `test_calc.py`.
- It writes a fixed `calc.py`.
- It reruns tests.
- It finishes with `DONE: Fixed calc.py`.

Confirm the fix:

```bash
cat "$tmpdir/calc.py"
```

Expected file content:

```python
def add(a, b):
    return a + b
```

## 6. Test The Demo Repository

Use the built-in demo repository for a quick manual task:

```bash
venv/bin/python main.py phase2 demo_repo \
  "Fix calculator.py so add(2, 3) returns 5."
```

Expected result: the agent should identify `calculator.py`, write a fix if needed,
run validation, and return success.

Note: if the demo file is already fixed, the agent may say no fix is needed.

## 7. Test The Web UI

Start the FastAPI server:

```bash
venv/bin/uvicorn server:app --reload --port 8000
```

Open:

```text
http://localhost:8000
```

Manual checks:

- The file tree loads.
- You can open and read files.
- You can submit an agent task.
- Streaming output appears while the agent runs.
- File diffs appear after edits.

## 8. Useful Failure Checks

Check whether Ollama is reachable:

```bash
venv/bin/python - <<'PY'
from utils.llm import check_ollama_available
print(check_ollama_available())
PY
```

If this prints `False`:

- Start Ollama with `ollama serve`.
- Pull the configured model with `ollama pull codellama`.
- Check `OLLAMA_MODEL` in `config.py` or your environment.

Check current git changes:

```bash
git status --short
git diff --check
```

`git diff --check` should print nothing.

## 9. What "Working" Means

The system is working when:

- Compile checks pass.
- `unittest discover` passes.
- `run_tests` returns `Return code: 0`.
- The live temporary-repo agent test fixes `return a - b` to `return a + b`.
- The web UI can stream an agent run without server errors.

This confirms the current autonomous loop:

```text
analyze repo -> build graph -> retrieve context -> plan -> edit -> run code -> run tests -> repeat
```

## 10. Known Limits To Keep In Mind

Passing these tests does not mean the agent is production-grade for every large
repository. The current system is ready for controlled repo-level experiments,
but larger projects still need stronger handling for dependency installation,
multi-package workspaces, flaky tests, large-file editing, and more robust patch
review.
