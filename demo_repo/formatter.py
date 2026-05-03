"""Formatter module — formats results for display."""


def format_result(label, value):
    """Format a label-value pair for display."""
    return f"[RESULT] {label}: {value}"


def format_table(rows):
    """Format a list of (label, value) tuples as a simple table."""
    if not rows:
        return "(empty)"
    max_label = max(len(r[0]) for r in rows)
    lines = []
    for label, value in rows:
        lines.append(f"  {label:<{max_label}}  |  {value}")
    return "\n".join(lines)
