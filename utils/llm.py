"""
AI Code Agent — LLM Interface
Handles all communication with Ollama (CodeLlama / Mistral).
"""

import json
import requests
from config import OLLAMA_BASE_URL, OLLAMA_MODEL, OLLAMA_TIMEOUT, LLM_TEMPERATURE, LLM_NUM_CTX
from utils.logger import log


def query_llm(prompt: str, system_prompt: str = "", expect_json: bool = False) -> str:
    """
    Send a prompt to Ollama and return the response text.
    If expect_json=True, attempts to extract valid JSON from the response.
    """
    url = f"{OLLAMA_BASE_URL}/api/generate"

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": LLM_TEMPERATURE,
            "num_ctx": LLM_NUM_CTX,
        },
    }

    if expect_json:
        payload["format"] = "json"

    if system_prompt:
        payload["system"] = system_prompt

    try:
        log("SYSTEM", f"Querying LLM ({OLLAMA_MODEL})...")
        resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        result = resp.json().get("response", "").strip()

        if expect_json:
            result = _extract_json(result)

        return result

    except requests.exceptions.ConnectionError:
        log("ERROR", f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Is Ollama running?")
        return ""
    except requests.exceptions.Timeout:
        log("ERROR", f"Ollama request timed out after {OLLAMA_TIMEOUT}s")
        return ""
    except Exception as e:
        log("ERROR", f"LLM query failed: {e}")
        return ""


def query_llm_json(prompt: str, system_prompt: str = "") -> dict:
    """
    Query the LLM and parse the response as JSON.
    Returns an empty dict on failure.
    """
    raw = query_llm(prompt, system_prompt=system_prompt, expect_json=True)
    if not raw:
        return {}

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log("ERROR", f"Failed to parse LLM JSON output:\n{raw[:300]}")
        return {}


def query_llm_chat(messages: list, expect_json: bool = True) -> str:
    """
    Multi-turn chat with Ollama (SWE-agent style).
    Sends the full message history and returns the assistant response.

    Args:
        messages: List of {"role": "system"|"user"|"assistant", "content": str}
        expect_json: Whether to request JSON formatted output

    Returns:
        Response text (or parsed JSON string if expect_json=True)
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"

    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": LLM_TEMPERATURE,
            "num_ctx": LLM_NUM_CTX,
        },
    }

    if expect_json:
        payload["format"] = "json"

    try:
        log("SYSTEM", f"Querying LLM chat ({OLLAMA_MODEL}, {len(messages)} messages)...")
        resp = requests.post(url, json=payload, timeout=OLLAMA_TIMEOUT)
        resp.raise_for_status()
        result = resp.json().get("message", {}).get("content", "").strip()

        if expect_json:
            result = _extract_json(result)

        return result

    except requests.exceptions.ConnectionError:
        log("ERROR", f"Cannot connect to Ollama at {OLLAMA_BASE_URL}")
        return ""
    except requests.exceptions.Timeout:
        log("ERROR", f"Ollama chat timed out after {OLLAMA_TIMEOUT}s")
        return ""
    except Exception as e:
        log("ERROR", f"LLM chat failed: {e}")
        return ""


def _extract_json(text: str) -> str:
    """
    Extract the first JSON object or array from LLM output.
    Handles markdown code fences and extraneous text.
    """
    # Strip markdown fences
    for fence in ["```json", "```JSON", "```"]:
        if fence in text:
            parts = text.split(fence)
            if len(parts) >= 2:
                text = parts[1].split("```")[0]
                break

    text = text.strip()

    # Find the first { or [
    start_obj = text.find("{")
    start_arr = text.find("[")

    if start_obj == -1 and start_arr == -1:
        return text

    if start_arr == -1 or (start_obj != -1 and start_obj < start_arr):
        start = start_obj
        open_char, close_char = "{", "}"
    else:
        start = start_arr
        open_char, close_char = "[", "]"

    # Balanced bracket extraction
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == open_char:
            depth += 1
        elif c == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return text[start:]


def check_ollama_available() -> bool:
    """Check if Ollama is running and the model is available."""
    try:
        resp = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m.get("name", "") for m in resp.json().get("models", [])]
        # Check if our model (possibly with :latest tag) is available
        available = any(
            OLLAMA_MODEL in m or m.startswith(OLLAMA_MODEL + ":")
            for m in models
        )
        if not available:
            log("ERROR", f"Model '{OLLAMA_MODEL}' not found. Available: {models}")
            log("INFO", f"Pull it with: ollama pull {OLLAMA_MODEL}")
        return available
    except Exception as e:
        log("ERROR", f"Ollama not reachable at {OLLAMA_BASE_URL}: {e}")
        return False
