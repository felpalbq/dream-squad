"""Retry com backoff exponencial para chamadas de API."""

import time
import functools
import logging
from typing import Callable, Type

logger = logging.getLogger(__name__)


def with_retry(
    max_attempts: int = 3,
    base_delay: float = 2.0,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
    label: str = "",
):
    """
    Decorator de retry com backoff exponencial.
    Uso: @with_retry(max_attempts=3, base_delay=2.0, label="Gemini API")

    Para contar retries reais, passe uma lista mutável como último
    argumento posicional da função decorada:
        retries = []
        @with_retry(...)
        def _call(retries):
            ...
        result = _call(retries)
        actual_retries = retries[0] if retries else 0
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            retry_count = 0
            for attempt in range(1, max_attempts + 1):
                try:
                    result = func(*args, **kwargs)
                    # Se a função recebeu uma lista mutável como último arg posicional
                    # ou como kwarg 'retries', registra o número de retries realizados.
                    if args and isinstance(args[-1], list):
                        args[-1].append(retry_count)
                    elif kwargs.get("retries") is not None and isinstance(kwargs.get("retries"), list):
                        kwargs["retries"].append(retry_count)
                    return result
                except exceptions as e:
                    last_exc = e
                    retry_count += 1
                    if attempt == max_attempts:
                        logger.error(
                            "[%s] Falhou após %d tentativas: %s",
                            label or func.__name__, max_attempts, e,
                        )
                        raise
                    delay = base_delay * (2 ** (attempt - 1))
                    logger.warning(
                        "[%s] Tentativa %d/%d falhou (%s). Retry em %.1fs.",
                        label or func.__name__, attempt, max_attempts, e, delay,
                    )
                    time.sleep(delay)
            raise last_exc
        return wrapper
    return decorator
