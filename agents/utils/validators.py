"""Validação de schemas YAML para outputs dos agentes. Usa Pydantic v2."""

import logging
from typing import Optional
from pydantic import BaseModel, field_validator

log = logging.getLogger(__name__)


class ResultadoPesquisa(BaseModel):
    tema: str
    titulo: str
    descricao: str
    url_fonte: Optional[str] = None
    data_hora: Optional[str] = None
    relevancia_nicho: Optional[int] = None
    origem: str  # gemini | tavily | ollama | apify | manual

    # Apify-specific
    engagement_score: Optional[float] = None
    post_type: Optional[str] = None
    hashtags: Optional[list[str]] = None
    perfil: Optional[str] = None
    curtidas: Optional[int] = None
    comentarios: Optional[int] = None

    # Manual-specific
    prioridade_operador: Optional[str] = None

    # Source signals (optional enrichment)
    sinal_friccao: Optional[str] = None
    sinal_transformacao: Optional[str] = None
    sinal_timing: Optional[str] = None

    @field_validator("relevancia_nicho")
    @classmethod
    def relevancia_range(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if not 0 <= v <= 10:
            raise ValueError(f"relevancia_nicho deve ser 0-10, recebido: {v}")
        return v

    @field_validator("prioridade_operador")
    @classmethod
    def prioridade_values(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in ("alta", "normal"):
            raise ValueError(f"prioridade_operador deve ser 'alta' ou 'normal', recebido: {v}")
        return v


class PesquisaFonte(BaseModel):
    """Schema unificado para todas as fontes de pesquisa."""
    client_id: str
    nicho: str
    data_pesquisa: str
    resultados: list[ResultadoPesquisa] = []
    status: Optional[str] = None
    erro: Optional[str] = None


# Aliases de compatibilidade para schemas específicos
PesquisaGemini = PesquisaFonte
PesquisaTavily = PesquisaFonte
PesquisaOllama = PesquisaFonte
PesquisaApify = PesquisaFonte
ManualInput = PesquisaFonte


def validate_yaml_output(data: dict, schema: type[BaseModel], label: str) -> None:
    """Valida um dict contra schema Pydantic. Levanta ValueError se inválido."""
    try:
        schema.model_validate(data)
    except (ValueError, TypeError) as e:
        log.error("[%s] Schema inválido: %s", label, e)
        raise ValueError(f"[{label}] Schema inválido: {e}") from e
