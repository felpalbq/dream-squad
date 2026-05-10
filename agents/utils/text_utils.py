"""Utilitários de processamento de texto para agentes LLM."""


def strip_fences(text: str) -> str:
    """Remove code fences markdown (```yaml / ```) do início/fim do texto."""
    text = text.strip()
    if text.startswith("```yaml"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
