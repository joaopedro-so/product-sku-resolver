"""
Serviço de monitoramento automático de produtos com progresso incremental.

Este módulo preserva o fluxo atual de resolução por alias, mas reorganiza a
execução em lote para suportar:
- construção prévia do plano de sync
- concorrência controlada
- callbacks de progresso em tempo real
- reaproveitamento de fetch entre variantes que compartilham a mesma página
"""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from backend.models.product import ProductRecord
from backend.models.sku_event import SkuEvent
from backend.services.datetime_service import (
    get_current_utc_datetime,
    parse_persisted_timestamp,
)
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from backend.utils.cached_fetcher import CachedFetcher
from history.history_store import HistoryStore


@dataclass(slots=True)
class MonitorRunPlan:
    """
    Responsabilidade:
        Descrever quais itens realmente entrarão na rodada de sincronização.

    Parâmetros:
        products_to_process: Variantes elegíveis para o ciclo atual.
        total_count: Quantidade total de itens que serão processados.
        skipped_count: Quantidade de itens ignorados por não serem elegíveis.

    Retorno:
        Estrutura leve usada antes da execução do job.

    Contexto de uso:
        Permite que a interface saiba o tamanho do lote antes de iniciar a
        sincronização e mantenha o total estável durante todo o progresso.
    """

    products_to_process: List[ProductRecord]
    total_count: int
    skipped_count: int


@dataclass(slots=True)
class MonitorItemResult:
    """
    Responsabilidade:
        Representar o resultado de sincronização de uma única variante.

    Parâmetros:
        alias: Alias interno da variante processada.
        product_name: Nome amigável usado na UI de progresso.
        status: Situação final da variante (`updated`, `unchanged` ou `failed`).
        old_sku: Código anterior da variante antes do sync.
        new_sku: Código final observado depois do sync.
        old_url: URL anterior usada como referência.
        new_url: URL final validada ou preservada.
        error_code: Código semântico da falha, quando existir.
        emitted_events: Eventos persistidos gerados para a variante.

    Retorno:
        Resultado consolidado por item.

    Contexto de uso:
        Alimenta o resumo final do job e permite distinguir claramente itens
        alterados, sem mudança e falhos.
    """

    alias: str
    product_name: str
    status: str
    old_sku: str
    new_sku: str
    old_url: str
    new_url: str
    error_code: Optional[str]
    emitted_events: List[SkuEvent] = field(default_factory=list)


@dataclass(slots=True)
class MonitorProgressUpdate:
    """
    Responsabilidade:
        Transportar um snapshot curto de progresso para observadores externos.

    Parâmetros:
        stage: Momento do ciclo (`started` ou `finished`).
        alias: Alias do item em foco na atualização.
        product_name: Nome amigável do item atual.
        total_count: Total estável de itens planejados para o job.
        processed_count: Quantidade já concluída até este instante.
        updated_count: Quantidade concluída com mudança detectada.
        unchanged_count: Quantidade concluída sem mudança.
        failed_count: Quantidade concluída com falha.
        current_item: Nome do item atualmente em execução ou recém-finalizado.
        item_status: Situação do item atual quando a etapa for `finished`.

    Retorno:
        Estrutura serializável e simples para callbacks de UI/job.

    Contexto de uso:
        Usada pelo serviço de job em background para alimentar a barra de
        progresso sem acoplar a camada de monitoramento à camada web.
    """

    stage: str
    alias: str
    product_name: str
    total_count: int
    processed_count: int
    updated_count: int
    unchanged_count: int
    failed_count: int
    current_item: str
    item_status: str = ""


@dataclass(slots=True)
class MonitorRunSummary:
    """
    Responsabilidade:
        Representar resumo completo da execução de monitoramento em lote.

    Parâmetros:
        processed_count: Quantidade total de produtos processados.
        success_count: Quantidade de resoluções concluídas sem erro.
        error_count: Quantidade de resoluções com falha.
        emitted_events: Eventos gerados durante a execução atual.
        total_count: Total planejado para o lote executado.
        updated_count: Quantidade de variantes que realmente mudaram.
        unchanged_count: Quantidade de variantes validadas sem mudança.
        failed_count: Quantidade de variantes com falha.
        skipped_count: Quantidade de variantes ignoradas antes do processamento.
        item_results: Resultado granular de cada item concluído.

    Retorno:
        Estrutura de observabilidade compatível com API/CLI/UI.

    Contexto de uso:
        Mantém retrocompatibilidade com os campos antigos do monitor e amplia
        o contrato para a nova UX de progresso em tempo real.
    """

    processed_count: int
    success_count: int
    error_count: int
    emitted_events: List[SkuEvent]
    total_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    item_results: List[MonitorItemResult] = field(default_factory=list)


class MonitorService:
    """
    Responsabilidade:
        Executar ciclo de monitoramento e registrar eventos de auditoria.

    Parâmetros:
        product_store: Serviço de leitura de produtos monitorados.
        resolver: Serviço de resolução de SKU/URL reutilizado sem duplicação.
        history_store: Serviço de persistência de eventos de monitoramento.

    Retorno:
        Serviço operacional para execução manual, agendada ou em background.

    Contexto de uso:
        Consumido por CLI, API, scheduler e agora também por jobs assíncronos
        do dashboard para sincronização em lote com progresso visual.
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
            Construído no runtime_context para reuso em API, CLI e dashboard.
        """

        self.product_store = product_store
        self.resolver = resolver
        self.history_store = history_store
        self.logger = logging.getLogger(__name__)

    def build_run_plan(self, skip_recent_seconds: int = 0) -> MonitorRunPlan:
        """
        Responsabilidade:
            Construir o lote real de itens elegíveis para a rodada atual.

        Parâmetros:
            skip_recent_seconds: Janela opcional para ignorar itens atualizados
                há pouco tempo, reduzindo fetch redundante em execuções seguidas.

        Retorno:
            MonitorRunPlan com itens processáveis e quantidade ignorada.

        Contexto de uso:
            A camada de job usa esse plano para exibir progresso estável antes
            mesmo do primeiro item terminar de sincronizar.
        """

        all_products = self.product_store.list_products()
        products_to_process: List[ProductRecord] = []
        skipped_count = 0
        reference_datetime = get_current_utc_datetime()

        for product in all_products:
            if not self._should_process_product(
                product=product,
                skip_recent_seconds=skip_recent_seconds,
                reference_datetime=reference_datetime,
            ):
                skipped_count += 1
                continue

            products_to_process.append(product)

        return MonitorRunPlan(
            products_to_process=products_to_process,
            total_count=len(products_to_process),
            skipped_count=skipped_count,
        )

    def run(
        self,
        max_workers: int = 1,
        skip_recent_seconds: int = 0,
        progress_callback: Optional[Callable[[MonitorProgressUpdate], None]] = None,
    ) -> MonitorRunSummary:
        """
        Responsabilidade:
            Executar monitoramento em lote usando plano e concorrência configuráveis.

        Parâmetros:
            max_workers: Quantidade máxima de workers concorrentes da rodada.
            skip_recent_seconds: Janela opcional para ignorar itens muito recentes.
            progress_callback: Callback opcional para progresso incremental.

        Retorno:
            MonitorRunSummary com contadores e eventos gerados.

        Contexto de uso:
            Mantém compatibilidade com chamadas antigas do monitor e agora
            também serve à UX assíncrona do dashboard.
        """

        run_plan = self.build_run_plan(skip_recent_seconds=skip_recent_seconds)
        return self.run_plan(
            run_plan=run_plan,
            max_workers=max_workers,
            progress_callback=progress_callback,
        )

    def run_plan(
        self,
        run_plan: MonitorRunPlan,
        max_workers: int = 1,
        progress_callback: Optional[Callable[[MonitorProgressUpdate], None]] = None,
    ) -> MonitorRunSummary:
        """
        Responsabilidade:
            Executar um plano já calculado com agregação de progresso e resumo.

        Parâmetros:
            run_plan: Plano de execução previamente calculado.
            max_workers: Quantidade máxima de workers concorrentes do lote.
            progress_callback: Callback opcional para observar o progresso.

        Retorno:
            MonitorRunSummary consolidado da rodada.

        Contexto de uso:
            Evita recalcular o mesmo lote quando a camada superior precisa
            saber o total antes de iniciar o processamento em background.
        """

        emitted_events: List[SkuEvent] = []
        item_results: List[MonitorItemResult] = []
        updated_count = 0
        unchanged_count = 0
        failed_count = 0
        processed_count = 0

        if run_plan.total_count == 0:
            return MonitorRunSummary(
                processed_count=0,
                success_count=0,
                error_count=0,
                emitted_events=[],
                total_count=0,
                updated_count=0,
                unchanged_count=0,
                failed_count=0,
                skipped_count=run_plan.skipped_count,
                item_results=[],
            )

        effective_workers = max(1, min(max_workers, run_plan.total_count))
        batch_resolver = self._build_batch_resolver()

        if effective_workers == 1:
            for product in run_plan.products_to_process:
                self._emit_progress_update(
                    progress_callback=progress_callback,
                    update=MonitorProgressUpdate(
                        stage="started",
                        alias=product.alias,
                        product_name=product.display_name,
                        total_count=run_plan.total_count,
                        processed_count=processed_count,
                        updated_count=updated_count,
                        unchanged_count=unchanged_count,
                        failed_count=failed_count,
                        current_item=product.display_name,
                    ),
                )
                item_result = self._process_single_product(product=product, resolver=batch_resolver)
                emitted_events.extend(item_result.emitted_events)
                item_results.append(item_result)
                processed_count += 1
                updated_count, unchanged_count, failed_count = self._accumulate_item_counters(
                    item_result=item_result,
                    updated_count=updated_count,
                    unchanged_count=unchanged_count,
                    failed_count=failed_count,
                )
                self._emit_progress_update(
                    progress_callback=progress_callback,
                    update=MonitorProgressUpdate(
                        stage="finished",
                        alias=item_result.alias,
                        product_name=item_result.product_name,
                        total_count=run_plan.total_count,
                        processed_count=processed_count,
                        updated_count=updated_count,
                        unchanged_count=unchanged_count,
                        failed_count=failed_count,
                        current_item=item_result.product_name,
                        item_status=item_result.status,
                    ),
                )
        else:
            with ThreadPoolExecutor(max_workers=effective_workers, thread_name_prefix="sync-job") as executor:
                future_map: dict[Future[MonitorItemResult], ProductRecord] = {}
                for product in run_plan.products_to_process:
                    future = executor.submit(self._process_single_product, product, batch_resolver)
                    future_map[future] = product
                    self._emit_progress_update(
                        progress_callback=progress_callback,
                        update=MonitorProgressUpdate(
                            stage="started",
                            alias=product.alias,
                            product_name=product.display_name,
                            total_count=run_plan.total_count,
                            processed_count=processed_count,
                            updated_count=updated_count,
                            unchanged_count=unchanged_count,
                            failed_count=failed_count,
                            current_item=product.display_name,
                        ),
                    )

                for completed_future in as_completed(future_map):
                    item_result = completed_future.result()
                    emitted_events.extend(item_result.emitted_events)
                    item_results.append(item_result)
                    processed_count += 1
                    updated_count, unchanged_count, failed_count = self._accumulate_item_counters(
                        item_result=item_result,
                        updated_count=updated_count,
                        unchanged_count=unchanged_count,
                        failed_count=failed_count,
                    )
                    self._emit_progress_update(
                        progress_callback=progress_callback,
                        update=MonitorProgressUpdate(
                            stage="finished",
                            alias=item_result.alias,
                            product_name=item_result.product_name,
                            total_count=run_plan.total_count,
                            processed_count=processed_count,
                            updated_count=updated_count,
                            unchanged_count=unchanged_count,
                            failed_count=failed_count,
                            current_item=item_result.product_name,
                            item_status=item_result.status,
                        ),
                    )

        return MonitorRunSummary(
            processed_count=processed_count,
            success_count=updated_count + unchanged_count,
            error_count=failed_count,
            emitted_events=emitted_events,
            total_count=run_plan.total_count,
            updated_count=updated_count,
            unchanged_count=unchanged_count,
            failed_count=failed_count,
            skipped_count=run_plan.skipped_count,
            item_results=item_results,
        )

    def _process_single_product(
        self,
        product: ProductRecord,
        resolver: ProductResolver,
    ) -> MonitorItemResult:
        """
        Responsabilidade:
            Sincronizar uma única variante e gerar os eventos operacionais dela.

        Parâmetros:
            product: Variante que será monitorada na rodada atual.
            resolver: Resolver usado pelo lote, possivelmente com cache de fetch.

        Retorno:
            MonitorItemResult com o resultado consolidado da variante.

        Contexto de uso:
            Mantém o corpo do job pequeno e previsível, facilitando execução
            serial ou paralela sem duplicar as regras de negócio.
        """

        old_sku = product.last_known_sku
        old_url = product.last_known_url
        resolver_result = resolver.resolve_sku_for_alias(product.alias)

        if not resolver_result.success:
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
            self.logger.warning(
                "Monitor falhou para alias=%s, erro=%s",
                product.alias,
                resolver_result.error_code,
            )
            return MonitorItemResult(
                alias=product.alias,
                product_name=product.display_name,
                status="failed",
                old_sku=old_sku,
                new_sku=old_sku,
                old_url=old_url,
                new_url=old_url,
                error_code=resolver_result.error_code,
                emitted_events=[error_event],
            )

        new_product = resolver_result.product
        if new_product is None:
            return MonitorItemResult(
                alias=product.alias,
                product_name=product.display_name,
                status="unchanged",
                old_sku=old_sku,
                new_sku=old_sku,
                old_url=old_url,
                new_url=old_url,
                error_code=None,
                emitted_events=[],
            )

        emitted_events: List[SkuEvent] = []
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

        return MonitorItemResult(
            alias=product.alias,
            product_name=new_product.display_name,
            status="updated" if emitted_events else "unchanged",
            old_sku=old_sku,
            new_sku=new_product.last_known_sku,
            old_url=old_url,
            new_url=new_product.last_known_url,
            error_code=None,
            emitted_events=emitted_events,
        )

    def _build_batch_resolver(self) -> ProductResolver:
        """
        Responsabilidade:
            Criar um resolver de lote com reaproveitamento de fetch entre variantes.

        Parâmetros:
            Nenhum.

        Retorno:
            ProductResolver pronto para a rodada atual.

        Contexto de uso:
            Em produtos agrupados, várias variantes compartilham a mesma página
            pai. O cache em memória reduz fetch redundante sem tocar na lógica
            principal de matching já existente.
        """

        if not isinstance(self.resolver, ProductResolver):
            return self.resolver

        base_fetcher = getattr(self.resolver, "fetcher", None)
        if base_fetcher is None or not hasattr(base_fetcher, "fetch_page"):
            return self.resolver

        return ProductResolver(
            product_store=self.product_store,
            fetcher=CachedFetcher(base_fetcher),
            search_provider=self.resolver.search_provider,
            search_match_threshold=self.resolver.search_match_threshold,
            max_search_candidates=self.resolver.max_search_candidates,
        )

    def _should_process_product(
        self,
        product: ProductRecord,
        skip_recent_seconds: int,
        reference_datetime,
    ) -> bool:
        """
        Responsabilidade:
            Decidir se uma variante deve entrar no lote atual do monitor.

        Parâmetros:
            product: Variante candidata a processamento.
            skip_recent_seconds: Janela opcional para pular itens recentes.
            reference_datetime: Instante de referência do início do plano.

        Retorno:
            True quando a variante deve ser processada; False quando deve ser
            ignorada para economizar tempo e evitar trabalho redundante.

        Contexto de uso:
            Centraliza as regras de exclusão do job para que a UI e o resumo
            final consigam explicar honestamente por que menos itens rodaram.
        """

        if not product.is_active:
            return False

        if not product.is_syncable:
            return False

        normalized_skip_window = max(0, int(skip_recent_seconds))
        if normalized_skip_window <= 0:
            return True

        last_matched_at = parse_persisted_timestamp(product.last_matched_at)
        if last_matched_at is None:
            return True

        elapsed_seconds = (reference_datetime - last_matched_at).total_seconds()
        return elapsed_seconds >= normalized_skip_window

    def _accumulate_item_counters(
        self,
        item_result: MonitorItemResult,
        updated_count: int,
        unchanged_count: int,
        failed_count: int,
    ) -> tuple[int, int, int]:
        """
        Responsabilidade:
            Atualizar os contadores agregados a partir do resultado de um item.

        Parâmetros:
            item_result: Resultado recém-concluído da variante.
            updated_count: Contador acumulado atual de itens alterados.
            unchanged_count: Contador acumulado atual de itens sem mudança.
            failed_count: Contador acumulado atual de itens com falha.

        Retorno:
            Tupla com os três contadores já incrementados.

        Contexto de uso:
            Mantém a leitura do laço principal limpa e reduz risco de divergência
            entre o resumo final e os snapshots intermediários de progresso.
        """

        if item_result.status == "updated":
            return updated_count + 1, unchanged_count, failed_count

        if item_result.status == "failed":
            return updated_count, unchanged_count, failed_count + 1

        return updated_count, unchanged_count + 1, failed_count

    def _emit_progress_update(
        self,
        progress_callback: Optional[Callable[[MonitorProgressUpdate], None]],
        update: MonitorProgressUpdate,
    ) -> None:
        """
        Responsabilidade:
            Entregar progresso incremental sem deixar callback quebrar o lote.

        Parâmetros:
            progress_callback: Callback opcional recebido da camada superior.
            update: Snapshot curto de progresso a ser emitido.

        Retorno:
            Nenhum.

        Contexto de uso:
            A UX de progresso não pode interromper o sync. Se a camada web
            falhar ao observar o job, o lote ainda precisa terminar normalmente.
        """

        if progress_callback is None:
            return

        try:
            progress_callback(update)
        except Exception as error:  # pragma: no cover - proteção operacional
            self.logger.warning("Falha ao emitir progresso do monitor: %s", error)

