"""
Modelo de evento de histórico para mudanças de SKU/URL e erros de monitoramento.

Este contrato padroniza auditoria do monitor automático com dados suficientes
para rastrear decisões e evolução de estado dos produtos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.services.datetime_service import get_current_utc_isoformat


@dataclass(slots=True)
class SkuEvent:
    """
    Responsabilidade:
        Representar evento de monitoramento persistido no histórico.

    Parâmetros:
        timestamp: Momento UTC ISO8601 da geração do evento.
        alias: Alias do produto relacionado ao evento.
        event_type: Tipo semântico (sku_changed, url_changed, error, etc.).
        old_sku: SKU anterior conhecido antes da execução.
        new_sku: SKU novo conhecido após a execução.
        old_url: URL anterior conhecida antes da execução.
        new_url: URL nova conhecida após a execução.
        match_score: Score de matching associado à decisão quando disponível.

    Retorno:
        Estrutura tipada para persistência e consulta de auditoria.

    Contexto de uso:
        Produzida pelo monitor_service e persistida via HistoryStore.
    """

    timestamp: str
    alias: str
    event_type: str
    old_sku: Optional[str]
    new_sku: Optional[str]
    old_url: Optional[str]
    new_url: Optional[str]
    match_score: Optional[float]

    @classmethod
    def create(
        cls,
        alias: str,
        event_type: str,
        old_sku: Optional[str],
        new_sku: Optional[str],
        old_url: Optional[str],
        new_url: Optional[str],
        match_score: Optional[float],
    ) -> "SkuEvent":
        """
        Responsabilidade:
            Construir evento com timestamp UTC padronizado.

        Parâmetros:
            alias: Alias do produto impactado pelo evento.
            event_type: Tipo semântico do evento registrado.
            old_sku: SKU antes da execução de monitoramento.
            new_sku: SKU depois da execução de monitoramento.
            old_url: URL antes da execução de monitoramento.
            new_url: URL depois da execução de monitoramento.
            match_score: Score de matching associado quando existir.

        Retorno:
            Instância de SkuEvent pronta para persistência.

        Contexto de uso:
            Atalho usado pelo monitor_service para criação consistente.
        """

        generated_timestamp = get_current_utc_isoformat()
        return cls(
            timestamp=generated_timestamp,
            alias=alias,
            event_type=event_type,
            old_sku=old_sku,
            new_sku=new_sku,
            old_url=old_url,
            new_url=new_url,
            match_score=match_score,
        )

    @classmethod
    def from_dict(cls, raw_item: Dict[str, Any]) -> "SkuEvent":
        """
        Responsabilidade:
            Reconstruir SkuEvent a partir de dicionário persistido.

        Parâmetros:
            raw_item: Objeto bruto vindo do arquivo JSON de histórico.

        Retorno:
            SkuEvent validado com campos opcionais normalizados.

        Contexto de uso:
            Usado pela camada history_store ao carregar eventos do disco.
        """

        return cls(
            timestamp=str(raw_item.get("timestamp", "")).strip(),
            alias=str(raw_item.get("alias", "")).strip(),
            event_type=str(raw_item.get("event_type", "")).strip(),
            old_sku=_optional_to_str(raw_item.get("old_sku")),
            new_sku=_optional_to_str(raw_item.get("new_sku")),
            old_url=_optional_to_str(raw_item.get("old_url")),
            new_url=_optional_to_str(raw_item.get("new_url")),
            match_score=_optional_to_float(raw_item.get("match_score")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Responsabilidade:
            Serializar evento para formato JSON persistível.

        Parâmetros:
            Nenhum.

        Retorno:
            Dicionário com campos do evento para gravação em arquivo.

        Contexto de uso:
            Chamado por HistoryStore.save_event durante escrita de histórico.
        """

        return {
            "timestamp": self.timestamp,
            "alias": self.alias,
            "event_type": self.event_type,
            "old_sku": self.old_sku,
            "new_sku": self.new_sku,
            "old_url": self.old_url,
            "new_url": self.new_url,
            "match_score": self.match_score,
        }


def _optional_to_str(raw_value: Any) -> Optional[str]:
    """
    Responsabilidade:
        Normalizar valor opcional para string com tratamento de vazio.

    Parâmetros:
        raw_value: Valor bruto possivelmente nulo vindo do JSON.

    Retorno:
        String limpa quando houver conteúdo; senão None.

    Contexto de uso:
        Auxiliar de validação na desserialização de eventos.
    """

    if raw_value is None:
        return None
    normalized_value = str(raw_value).strip()
    return normalized_value or None


def _optional_to_float(raw_value: Any) -> Optional[float]:
    """
    Responsabilidade:
        Normalizar valor opcional para float de forma segura.

    Parâmetros:
        raw_value: Valor bruto de score vindo do JSON.

    Retorno:
        Float convertido quando possível; None em ausência/erro.

    Contexto de uso:
        Auxiliar para leitura resiliente de histórico legado.
    """

    if raw_value is None:
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None
