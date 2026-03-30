"""
Serviço de monitoramento automático de produtos com geração de eventos.

Este módulo orquestra a execução do resolver em lote e registra histórico de
mudanças de SKU/URL e falhas controladas para auditoria.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List

from backend.models.sku_event import SkuEvent
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from history.history_store import HistoryStore


@dataclass(slots=True)
class MonitorRunSummary:
    """
    Responsabilidade:
        Representar resumo da execução de monitoramento em lote.

    Parâmetros:
        processed_count: Quantidade total de produtos processados.
        success_count: Quantidade de resoluções com sucesso.
        error_count: Quantidade de resoluções com falha.
        emitted_events: Eventos gerados durante a execução atual.

    Retorno:
        Estrutura de observabilidade para API/CLI e logs.

    Contexto de uso:
        Retornada pelo monitor_service ao final de cada execução.
    """

    processed_count: int
    success_count: int
    error_count: int
    emitted_events: List[SkuEvent]


class MonitorService:
    """
    Responsabilidade:
        Executar ciclo de monitoramento e registrar eventos de auditoria.

    Parâmetros:
        product_store: Serviço de leitura de produtos monitorados.
        resolver: Serviço de resolução de SKU/URL reutilizado sem duplicação.
        history_store: Serviço de persistência de eventos de monitoramento.

    Retorno:
        Serviço operacional para execução manual ou agendada.

    Contexto de uso:
        Consumido por CLI, API e scheduler para monitoramento contínuo.
    """

    def __init__(
        self,
        product_store: ProductStoreService,
        resolver: ProductResolver,
        history_store: HistoryStore,
    ) -> None:
        """
        Responsabilidade:
            Inicializar dependências e logger da execução de monitoramento.

        Parâmetros:
            product_store: Camada de acesso ao catálogo persistido.
            resolver: Camada de resolução de SKU com validação de identidade.
            history_store: Camada de persistência de eventos de auditoria.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construído no runtime_context para reuso em API/CLI/scheduler.
        """

        self.product_store = product_store
        self.resolver = resolver
        self.history_store = history_store
        self.logger = logging.getLogger(__name__)

    def run(self) -> MonitorRunSummary:
        """
        Responsabilidade:
            Executar monitoramento em lote para todos os produtos cadastrados.

        Parâmetros:
            Nenhum.

        Retorno:
            MonitorRunSummary com contadores e eventos gerados.

        Contexto de uso:
            Método principal chamado por endpoint /monitor/run e scheduler.
        """

        products = self.product_store.list_products()
        emitted_events: List[SkuEvent] = []
        success_count = 0
        error_count = 0

        for product in products:
            old_sku = product.last_known_sku
            old_url = product.last_known_url

            resolver_result = self.resolver.resolve_sku_for_alias(product.alias)
            if not resolver_result.success:
                error_count += 1

                # Tratamento de erro:
                # Registramos evento de falha para manter rastreabilidade de
                # execução e facilitar investigação operacional posterior.
                error_event = SkuEvent.create(
                    alias=product.alias,
                    event_type="error",
                    old_sku=old_sku,
                    new_sku=old_sku,
                    old_url=old_url,
                    new_url=old_url,
                    match_score=resolver_result.match_result.score if resolver_result.match_result else None,
                )
                self.history_store.save_event(error_event)
                emitted_events.append(error_event)

                self.logger.warning(
                    "Monitor falhou para alias=%s, erro=%s",
                    product.alias,
                    resolver_result.error_code,
                )
                continue

            success_count += 1
            new_product = resolver_result.product
            if new_product is None:
                continue

            # Regra de negócio:
            # Mudanças são registradas em eventos separados para permitir
            # consultas específicas por tipo (sku_changed/url_changed).
            if old_sku != new_product.last_known_sku:
                sku_event = SkuEvent.create(
                    alias=product.alias,
                    event_type="sku_changed",
                    old_sku=old_sku,
                    new_sku=new_product.last_known_sku,
                    old_url=old_url,
                    new_url=new_product.last_known_url,
                    match_score=resolver_result.match_result.score if resolver_result.match_result else None,
                )
                self.history_store.save_event(sku_event)
                emitted_events.append(sku_event)

            if old_url != new_product.last_known_url:
                url_event = SkuEvent.create(
                    alias=product.alias,
                    event_type="url_changed",
                    old_sku=old_sku,
                    new_sku=new_product.last_known_sku,
                    old_url=old_url,
                    new_url=new_product.last_known_url,
                    match_score=resolver_result.match_result.score if resolver_result.match_result else None,
                )
                self.history_store.save_event(url_event)
                emitted_events.append(url_event)

        return MonitorRunSummary(
            processed_count=len(products),
            success_count=success_count,
            error_count=error_count,
            emitted_events=emitted_events,
        )
