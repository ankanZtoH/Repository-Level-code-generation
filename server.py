"""
AuraCode — FastAPI Server
=========================
Wraps the existing autonomous coding agent with HTTP API endpoints.
Provides real-time streaming of agent steps via Server-Sent Events (SSE).
Includes diff tracking for every file modification.
"""

import os
import sys
import re
import json
import difflib
import threading
import queue
import time
import traceback

# Ensure project root is on the path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

import config
from utils.llm import check_ollama_available
from utils.file_ops import read_file, write_file, list_files
from phase2.tools import execute_tool, SUPPORTED_EXTENSIONS


# ─── ANSI Escape Stripper ───────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m|\033\[[0-9;]*m|\x1b\[[\d;]*[a-zA-Z]")

def _strip_ansi(text: str) -> str:
    """Remove ANSI color codes from text."""
    # Also remove leftover bracket sequences like [2m, [0m, [93m etc.
    text = _ANSI_RE.sub("", text)
    # Catch any residual partial codes
    text = re.sub(r'\[[\d;]*m', '', text)
    return text


# ─── App Setup ──────────────────────────────────────────────

app = FastAPI(title="AuraCode", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Request/Response Models ────────────────────────────────

class TaskRequest(BaseModel):
    task: str
    repo_path: str

class WriteFileRequest(BaseModel):
    path: str
    content: str

class SetModelRequest(BaseModel):
    model: str


# ─── Diff Tracker ───────────────────────────────────────────

class DiffTracker:
    """
    Tracks file contents before/after agent edits.
    Computes line-level diffs for the frontend.
    """

    def __init__(self):
        self._snapshots = {}  # path -> original content

    def snapshot(self, path: str):
        """Store the current file content as the 'before' state."""
        try:
            abs_path = os.path.abspath(path)
            if os.path.isfile(abs_path):
                with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                    self._snapshots[abs_path] = f.read()
            else:
                self._snapshots[abs_path] = ""
        except Exception:
            self._snapshots[os.path.abspath(path)] = ""

    def compute_diff(self, path: str) -> dict:
        """Compare stored snapshot with current file content."""
        abs_path = os.path.abspath(path)
        original = self._snapshots.get(abs_path, "")

        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                current = f.read()
        except Exception:
            current = ""

        if original == current:
            return None

        orig_lines = original.splitlines()
        curr_lines = current.splitlines()

        diff_lines = []
        added = 0
        removed = 0

        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, orig_lines, curr_lines
        ).get_opcodes():
            if tag == "replace":
                for line in orig_lines[i1:i2]:
                    diff_lines.append(f"- {line}")
                    removed += 1
                for line in curr_lines[j1:j2]:
                    diff_lines.append(f"+ {line}")
                    added += 1
            elif tag == "delete":
                for line in orig_lines[i1:i2]:
                    diff_lines.append(f"- {line}")
                    removed += 1
            elif tag == "insert":
                for line in curr_lines[j1:j2]:
                    diff_lines.append(f"+ {line}")
                    added += 1

        return {
            "file": os.path.basename(abs_path),
            "path": os.path.relpath(abs_path),
            "added": added,
            "removed": removed,
            "diff": diff_lines[:50],  # cap to prevent huge payloads
        }

    def clear(self):
        self._snapshots.clear()


# ─── Agent Runner with Streaming ────────────────────────────

class StreamingAgentRunner:
    """
    Runs the agent in a background thread and captures all
    print output + diff results into a queue for SSE streaming.
    """

    def __init__(self):
        self.event_queue = queue.Queue()
        self.diff_tracker = DiffTracker()

    def _emit(self, event_type: str, data: dict):
        self.event_queue.put({"type": event_type, **data})

    def run_task(self, task: str, repo_path: str):
        """Run the agent task in a background thread."""

        def _worker():
            import builtins
            original_print = builtins.print

            # Monkey-patch print to capture agent output (strip ANSI codes)
            def patched_print(*args, **kwargs):
                text = " ".join(str(a) for a in args)
                clean = _strip_ansi(text).strip()
                if clean:
                    self._emit("log", {"message": clean})
                original_print(*args, **kwargs)

            try:
                builtins.print = patched_print
                self._emit("status", {"message": "Agent starting..."})

                abs_repo = os.path.abspath(repo_path)

                # Snapshot all files in the repo before the agent runs
                self._snapshot_repo(abs_repo)

                # Patch execute_tool at BOTH module AND agent level.
                # agent.py does `from phase2.tools import execute_tool` at load time,
                # so it holds its own reference. We must patch both.
                from phase2 import tools as tools_module
                from phase2 import agent as agent_module
                original_execute_tools = tools_module.execute_tool
                original_execute_agent = agent_module.execute_tool

                def tracked_execute(action, rp="."):
                    tool_name = action.get("tool", action.get("action", ""))
                    path = action.get("path", "")

                    # Before write: snapshot the file
                    if tool_name in ("write_file", "create_file") and path:
                        full = os.path.join(rp, path) if not os.path.isabs(path) else path
                        self.diff_tracker.snapshot(full)

                    result = original_execute_tools(action, rp)

                    # After write: compute and emit diff
                    if tool_name in ("write_file", "create_file") and path:
                        full = os.path.join(rp, path) if not os.path.isabs(path) else path
                        diff = self.diff_tracker.compute_diff(full)
                        if diff:
                            self._emit("diff", diff)

                    # Emit tool result
                    self._emit("tool", {
                        "tool": tool_name,
                        "path": path,
                        "result": _strip_ansi(result[:500]) if result else "",
                    })

                    return result

                # Patch both references
                tools_module.execute_tool = tracked_execute
                agent_module.execute_tool = tracked_execute

                # Actually run the agent
                from phase2.agent import run_agent
                result = run_agent(task, repo_path)

                # Restore both references
                tools_module.execute_tool = original_execute_tools
                agent_module.execute_tool = original_execute_agent

                self._emit("result", {
                    "success": result.get("success", False),
                    "summary": result.get("summary", ""),
                    "steps": result.get("steps", 0),
                })

            except Exception as e:
                self._emit("error", {"message": str(e), "traceback": traceback.format_exc()})
            finally:
                builtins.print = original_print
                self._emit("done", {"message": "Agent finished"})

        thread = threading.Thread(target=_worker, daemon=True)
        thread.start()

    def _snapshot_repo(self, repo_path: str):
        """Take a snapshot of all files before the agent starts."""
        try:
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__" and d != "venv"]
                for fname in files:
                    fpath = os.path.join(root, fname)
                    self.diff_tracker.snapshot(fpath)
        except Exception:
            pass

    def stream_events(self):
        """Generator that yields SSE events."""
        while True:
            try:
                event = self.event_queue.get(timeout=120)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "done":
                    break
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"


# ─── Global runner instance ─────────────────────────────────
runner = StreamingAgentRunner()


# ─── API Endpoints ──────────────────────────────────────────

@app.get("/api/status")
def get_status():
    """Check if Ollama is available and return current model."""
    available = check_ollama_available()
    return {
        "ollama_available": available,
        "model": config.OLLAMA_MODEL,
    }


@app.get("/api/models")
def get_models():
    """List available Ollama models."""
    import requests as req
    try:
        resp = req.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        return {"models": models, "current": config.OLLAMA_MODEL}
    except Exception as e:
        return {"models": [], "current": config.OLLAMA_MODEL, "error": str(e)}


@app.post("/api/set_model")
def set_model(req: SetModelRequest):
    """Change the active Ollama model at runtime."""
    config.OLLAMA_MODEL = req.model
    return {"model": config.OLLAMA_MODEL, "status": "ok"}


@app.get("/api/file_tree")
def get_file_tree(path: str = ""):
    """Return the file tree of a directory."""
    if not path:
        return {"error": "path parameter required"}

    abs_path = os.path.abspath(path)
    if not os.path.isdir(abs_path):
        return {"error": f"Not a directory: {path}"}

    tree = _build_file_tree(abs_path)
    return {"root": abs_path, "tree": tree}


@app.get("/api/read_file")
def api_read_file(path: str = ""):
    """Read a file and return its content."""
    if not path:
        return {"error": "path parameter required"}

    abs_path = os.path.abspath(path)
    if not os.path.isfile(abs_path):
        return {"error": f"File not found: {path}"}

    content = read_file(abs_path)
    ext = os.path.splitext(abs_path)[1].lower()

    # Detect language for syntax highlighting
    lang_map = {
        ".py": "python", ".js": "javascript", ".ts": "typescript",
        ".java": "java", ".c": "c", ".cpp": "cpp", ".h": "c",
        ".html": "html", ".css": "css", ".json": "json",
        ".md": "markdown", ".sh": "bash", ".rb": "ruby",
    }

    return {
        "path": abs_path,
        "name": os.path.basename(abs_path),
        "content": content,
        "language": lang_map.get(ext, "text"),
    }


@app.post("/api/write_file")
def api_write_file(req: WriteFileRequest):
    """Write content to a file."""
    abs_path = os.path.abspath(req.path)
    success = write_file(abs_path, req.content)
    return {"success": success, "path": abs_path}


@app.post("/api/run_task")
def run_task(req: TaskRequest):
    """
    Start an agent task. Returns an SSE stream of events.
    The frontend should call this and read the event stream.
    """
    global runner
    runner = StreamingAgentRunner()
    runner.run_task(req.task, req.repo_path)

    return StreamingResponse(
        runner.stream_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── File Tree Builder ──────────────────────────────────────

SKIP_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", ".DS_Store"}

def _build_file_tree(root: str, max_depth: int = 5, current_depth: int = 0) -> list:
    """Build a nested file tree structure."""
    if current_depth >= max_depth:
        return []

    entries = []
    try:
        items = sorted(os.listdir(root))
    except PermissionError:
        return []

    dirs_first = sorted(items, key=lambda x: (not os.path.isdir(os.path.join(root, x)), x.lower()))

    for name in dirs_first:
        if name in SKIP_DIRS or name.startswith("."):
            continue

        full_path = os.path.join(root, name)

        if os.path.isdir(full_path):
            children = _build_file_tree(full_path, max_depth, current_depth + 1)
            entries.append({
                "name": name,
                "path": full_path,
                "type": "directory",
                "children": children,
            })
        elif os.path.isfile(full_path):
            entries.append({
                "name": name,
                "path": full_path,
                "type": "file",
                "size": os.path.getsize(full_path),
            })

    return entries


# ─── Serve Frontend ─────────────────────────────────────────

FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/style.css")
def serve_css():
    return FileResponse(os.path.join(FRONTEND_DIR, "style.css"), media_type="text/css")

@app.get("/app.js")
def serve_js():
    return FileResponse(os.path.join(FRONTEND_DIR, "app.js"), media_type="application/javascript")


# ─── Main ───────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    print(f"\n  AuraCode Server starting...")
    print(f"  Open http://localhost:8000 in your browser\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
