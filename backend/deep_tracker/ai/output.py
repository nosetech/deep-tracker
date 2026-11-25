def strip_code_fence(text: str) -> str:
    """AIの出力がコードブロック（```）で囲まれていたら外す。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines[1:])
    return text.strip()
