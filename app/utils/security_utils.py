def mask_sensitive_data(text: str, visible_chars: int = 4) -> str:
    """แปลง '1234567890' -> '******7890'"""
    if not text or len(text) <= visible_chars:
        return text
    return '*' * (len(text) - visible_chars) + text[-visible_chars:]