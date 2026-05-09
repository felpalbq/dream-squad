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
    relevancia_nicho: int
    origem: str  # gemini | tavily | ollama | apify | manual

    @field_validator("relevancia_nicho")
    @classmethod
    def relevancia_range(cls, v: int) -> int:
        if not 0 <= v <= 10:
            raise ValueError(f"relevancia_nicho deve ser 0-10, recebido: {v}")
        return v


class PesquisaGemini(BaseModel):
    client_id: str
    nicho: str
    data_pesquisa: str
    resultados: list[ResultadoPesquisa] = []
    status: Optional[str] = None
    erro: Optional[str] = None


class PesquisaTavily(BaseModel):
    client_id: str
    nicho: str
    data_pesquisa: str
    resultados: list[ResultadoPesquisa] = []
    status: Optional[str] = None
    erro: Optional[str] = None


class PesquisaOllama(BaseModel):
    client_id: str
    nicho: str
    data_pesquisa: str
    resultados: list[ResultadoPesquisa] = []
    status: Optional[str] = None
    erro: Optional[str] = None


class PesquisaApify(BaseModel):
    client_id: str
    nicho: str
    data_pesquisa: str
    resultados: list[ResultadoPesquisa] = []
    status: Optional[str] = None
    erro: Optional[str] = None


class ManualInput(BaseModel):
    client_id: str
    data_pesquisa: str
    resultados: list[ResultadoPesquisa] = []


def validate_yaml_output(data: dict, schema: type[BaseModel], label: str) -> bool:
    """Valida um dict contra um schema Pydantic. Retorna True se válido."""
    try:
        schema.model_validate(data)
        return True
    except Exception as e:
        log.error("[%s] Schema inválido: %s", label, e)
        return False
