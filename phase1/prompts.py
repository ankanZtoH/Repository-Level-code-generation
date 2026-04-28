# """
# AI Code Agent — Phase 1 Prompts
# Prompt templates for direct code editing (no agent loop).
# """

# # SYSTEM_PROMPT_EDITOR = """You are an expert code editor AI. You receive code and an instruction.
# # You MUST return ONLY the complete updated code — nothing else.
# # Do NOT include explanations, markdown fences, or commentary.
# # Return ONLY the raw code that should replace the original."""


# # def build_edit_prompt(instruction: str, code: str, language: str = "python") -> str:
# #     """Build a prompt for Phase 1 direct code editing."""
# #     return f"""## Instruction
# # {instruction}

# # ## Original Code ({language})
# # {code}

# # ## Updated Code
# # Return ONLY the complete updated code below:"""

# SYSTEM_PROMPT_EDITOR = """You are a code editor. Return ONLY the complete updated code. No explanations, no markdown fences."""


# def build_edit_prompt(instruction: str, code: str, language: str = "python") -> str:
#     return f"""Instruction: {instruction}

# {language}:
# {code}

# Updated code:"""


# SYSTEM_PROMPT_MULTI_FILE = """You are an expert code editor AI. You receive multiple files and an instruction.
# You MUST return a JSON object where each key is a filename and each value is the full updated content of that file.
# Return ONLY valid JSON — no markdown fences, no explanations."""


# def build_multi_file_prompt(instruction: str, files: dict) -> str:
#     """
#     Build a prompt for multi-file editing.
#     files: {filename: content}
#     """
#     file_sections = []
#     for fname, content in files.items():
#         file_sections.append(f"### {fname}\n```\n{content}\n```")

#     files_text = "\n\n".join(file_sections)

#     return f"""## Instruction
# {instruction}

# ## Files
# {files_text}

# ## Updated Files (JSON)
# Return a JSON object mapping filename → updated content:"""




"""
AI Code Agent — Phase 1 Prompts
"""

SYSTEM_PROMPT_EDITOR = """You are a code editor. Return ONLY the complete updated code. No explanations, no markdown fences."""

SYSTEM_PROMPT_MULTI_FILE = """You are a code editor. Return ONLY a JSON object: {filename: updated_content}. No markdown, no explanation."""


def build_edit_prompt(instruction: str, code: str, language: str = "python") -> str:
    return f"""Instruction: {instruction}

{language}:
{code}

Updated code:"""


def build_multi_file_prompt(instruction: str, files: dict) -> str:
    sections = "\n\n".join(f"### {name}\n{content}" for name, content in files.items())
    return f"""Instruction: {instruction}

{sections}

JSON output:"""