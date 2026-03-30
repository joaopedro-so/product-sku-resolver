"""
Fábrica de contexto de execução para API, CLI e monitoramento.

Este módulo centraliza criação de dependências para garantir reuso consistente
entre interfaces e evitar duplicação de regras operacionais.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from config import MATCH_THRESHOLD, MAX_SEARCH_RESULTS
from history.history_store import HistoryStore
from monitoring.monitor_service import MonitorService
from backend.search.renner_provider import RennerSearchProvider
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from backend.utils.fetcher import Fetcher


@dataclass(slots=True)
class RuntimeServices:
    """
    Responsabilidade:
        Agrupar serviços compartilhados usados por API, CLI e scheduler.

    Parâmetros:
        product_store: Serviço de persistência de produtos em JSON.
        resolver: Serviço de resolução de SKU com fallback de busca.
        history_store: Serviço de persistência de eventos de monitoramento.
        monitor_service: Serviço de execução de monitoramento em lote.

    Retorno:
        Container simples para injeção de dependências nas interfaces.

    Contexto de uso:
        Retornado por build_runtime_services no bootstrap da aplicação.
    """

    product_store: ProductStoreService
    resolver: ProductResolver
    history_store: HistoryStore
    monitor_service: MonitorService


def _resolve_storage_path(configured_storage_path: str | None = None) -> Path:
    """
    Responsabilidade:
        Definir caminho do storage de produtos com prioridade de override.

    Parâmetros:
        configured_storage_path: Caminho opcional recebido por API/CLI/testes.

    Retorno:
        Path para o arquivo de produtos.

    Contexto de uso:
        Evita divergência de configuração entre interfaces.
    """

    if configured_storage_path and configured_storage_path.strip():
        return Path(configured_storage_path.strip())

    env_storage_path = os.getenv("PRODUCT_STORAGE_FILE", "").strip()
    if env_storage_path:
        return Path(env_storage_path)

    return Path("data/products.json")


def _resolve_history_path(configured_history_path: str | None = None) -> Path:
    """
    Responsabilidade:
        Definir caminho do storage de histórico com prioridade de override.

    Parâmetros:
        configured_history_path: Caminho opcional do arquivo de histórico.

    Retorno:
        Path para arquivo JSON de eventos.

    Contexto de uso:
        Usado por API/CLI para compartilhar o mesmo histórico persistido.
    """

    if configured_history_path and configured_history_path.strip():
        return Path(configured_history_path.strip())

    env_history_path = os.getenv("PRODUCT_HISTORY_FILE", "").strip()
    if env_history_path:
        return Path(env_history_path)

    return Path("data/history.json")


def build_runtime_services(
    configured_storage_path: str | None = None,
    configured_history_path: str | None = None,
) -> RuntimeServices:
    """
    Responsabilidade:
        Construir serviços compartilhados por API, CLI e monitoramento.

    Parâmetros:
        configured_storage_path: Override opcional do arquivo de produtos.
        configured_history_path: Override opcional do arquivo de histórico.

    Retorno:
        RuntimeServices com dependências prontas para uso.

    Contexto de uso:
        Chamada de bootstrap central para padronizar runtime da aplicação.
    """

    storage_path = _resolve_storage_path(configured_storage_path)
    history_path = _resolve_history_path(configured_history_path)

    product_store_service = ProductStoreService(storage_path)
    history_store_service = HistoryStore(history_path)

    shared_fetcher = Fetcher()
    search_provider = RennerSearchProvider(max_results=MAX_SEARCH_RESULTS)

    resolver_service = ProductResolver(
        product_store=product_store_service,
        fetcher=shared_fetcher,
        search_provider=search_provider,
        search_match_threshold=MATCH_THRESHOLD,
        max_search_candidates=MAX_SEARCH_RESULTS,
    )

    monitor_service = MonitorService(
        product_store=product_store_service,
        resolver=resolver_service,
        history_store=history_store_service,
    )

    return RuntimeServices(
        product_store=product_store_service,
        resolver=resolver_service,
        history_store=history_store_service,
        monitor_service=monitor_service,
    )
