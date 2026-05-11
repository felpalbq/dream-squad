"""Utilitários de processamento de texto para agentes LLM."""

import re


def strip_fences(text: str) -> str:
    """Remove code fences markdown (```yaml / ``` / ~~~yaml / ~~~) do início/fim do texto."""
    text = text.strip()
    text = re.sub(r"^```(?:yaml|json|python)?\s*", "", text)
    text = re.sub(r"^~~~(?:yaml|json|python)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"\s*~~~$", "", text)
    return text.strip()
