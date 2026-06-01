"""Code block detection heuristic."""


def is_code_block(text: str) -> bool:
    text = text.strip()
    lines = text.split("\n")

    if text.startswith("```") or text.endswith("```"):
        return True
    if text.startswith("`") and text.endswith("`") and len(text) > 2:
        return True
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        return True

    code_patterns = [
        "def ", "function ", "const ", "let ", "var ", "=>", "async ", "await "
    ]
    if any(p in text for p in code_patterns):
        return True

    if len(lines) > 2:
        indented = sum(
            1 for l in lines if l.startswith("    ") or l.startswith("\t")
        )
        if indented >= len(lines) * 0.5:
            return True

    code_chars = sum(text.count(c) for c in ["{", "}", "(", ")", ";", ":", "="])
    if len(text) > 0 and code_chars / len(text) > 0.15:
        return True

    return False
