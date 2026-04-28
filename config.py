"""
AI Code Agent — Configuration
Central configuration for the entire system.
"""

import os

# ─── Ollama Settings ────────────────────────────────────────
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "codellama")  # or "mistral"
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "120"))

# ─── Agent Settings ─────────────────────────────────────────
MAX_AGENT_STEPS = int(os.getenv("MAX_AGENT_STEPS", "15"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))

# ─── Logging ────────────────────────────────────────────────
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FILE = os.getenv("LOG_FILE", "agent.log")

# ─── Paths ──────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DEMO_REPO_DIR = os.path.join(PROJECT_ROOT, "demo_repo")

# ─── LLM Generation Parameters ─────────────────────────────
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
LLM_NUM_CTX = int(os.getenv("LLM_NUM_CTX", "8192"))
