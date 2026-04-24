"""
AI Code Agent — Structured Logger
Provides color-coded, step-by-step logging for the agent pipeline.
"""

import sys
import datetime


# ─── ANSI Colors ────────────────────────────────────────────
class Colors:
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"

    RED     = "\033[91m"
    GREEN   = "\033[92m"
    YELLOW  = "\033[93m"
    BLUE    = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN    = "\033[96m"
    WHITE   = "\033[97m"

    BG_RED    = "\033[41m"
    BG_GREEN  = "\033[42m"
    BG_BLUE   = "\033[44m"
    BG_YELLOW = "\033[43m"


# ─── Tag → Color Mapping ───────────────────────────────────
TAG_STYLES = {
    "THOUGHT":      (Colors.CYAN,    "🧠"),
    "ACTION":       (Colors.YELLOW,  "⚡"),
    "OBSERVATION":  (Colors.GREEN,   "👁️"),
    "RESULT":       (Colors.MAGENTA, "✅"),
    "ERROR":        (Colors.RED,     "❌"),
    "PLAN":         (Colors.BLUE,    "📋"),
    "TOOL":         (Colors.YELLOW,  "🔧"),
    "DIFF":         (Colors.GREEN,   "📝"),
    "INFO":         (Colors.WHITE,   "ℹ️"),
    "STEP":         (Colors.CYAN,    "👣"),
    "FEEDBACK":     (Colors.RED,     "🔄"),
    "SYSTEM":       (Colors.BLUE,    "⚙️"),
    "CONTEXT":      (Colors.DIM,     "📂"),
}


def _timestamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


def log(tag: str, message: str, indent: int = 0):
    """Print a structured, color-coded log line."""
    color, icon = TAG_STYLES.get(tag.upper(), (Colors.WHITE, "•"))
    prefix = "  " * indent
    ts = _timestamp()

    header = f"{Colors.DIM}[{ts}]{Colors.RESET} {color}{Colors.BOLD}[{tag.upper()}]{Colors.RESET} {icon}"
    lines = message.strip().split("\n")

    # First line
    print(f"{prefix}{header}  {lines[0]}")
    # Continuation lines
    for line in lines[1:]:
        print(f"{prefix}       {color}{line}{Colors.RESET}")

    sys.stdout.flush()


def separator(title: str = ""):
    """Print a visual separator."""
    line = "─" * 60
    if title:
        print(f"\n{Colors.BOLD}{Colors.BLUE}{'─'*5} {title} {'─' * (53 - len(title))}{Colors.RESET}")
    else:
        print(f"\n{Colors.DIM}{line}{Colors.RESET}")
    sys.stdout.flush()


def banner(text: str):
    """Print a large banner."""
    width = 60
    pad = (width - len(text) - 2) // 2
    print(f"\n{Colors.BG_BLUE}{Colors.WHITE}{Colors.BOLD}")
    print(f"{'█' * width}")
    print(f"█{' ' * pad}{text}{' ' * (width - pad - len(text) - 2)}█")
    print(f"{'█' * width}")
    print(f"{Colors.RESET}\n")
    sys.stdout.flush()
