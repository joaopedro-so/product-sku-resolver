"""
Testes unitários do serviço de monitoramento automático.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.datetime_service import get_current_utc_isoformat
from backend.services.product_store_service import ProductStoreService
from history.history_store import HistoryStore
from monitoring.monitor_service import MonitorService


class FakeResolverMonitor:
    """
    Responsabilidade:
        Simular resolver com cenários de mudança e erro para monitor_service.

    Parâmetros:
        store: Serviço de storage para mutações simuladas por alias.

    Retorno:
        Instância fake compatível com método resolve_sku_for_alias.

    Contexto de uso:
        Permite cobrir regras de emissão de eventos sem rede externa.
    """

    def __init__(self, store: ProductStoreService) -> None:
        """
        Responsabilidade:
            Inicializar fake com referência ao storage de produtos.

        Parâmetros:
            store: ProductStoreService com produtos de teste.

        Retorno:
            Nenhum.

        Contexto de uso:
            Setup do fake resolver para cenários monitorados.
        """

        self.store = store

    def resolve_sku_for_alias(self, product_alias: str):
        """
        Responsabilidade:
            Simular resultado do resolver conforme alias solicitado.

        Parâmetros:
            product_alias: Alias do produto processado no monitoramento.

        Retorno:
            Objeto com interface compatível ao ResolveResult real.

        Contexto de uso:
            Exercita emissão de eventos sku_changed/url_changed/error.
        """

        if product_alias == "item_error":
            return type(
                "ResolveResultLike",
                (),
                {
                    "success": False,
                    "message": "Falha simulada",
                    "error_code": "FETCH_FAILED",
                    "product": None,
                    "match_result": None,
                },
            )()

        updated_product = self.store.update_product_sku_and_url(
            product_alias=product_alias,
            new_sku="SKU-NOVO",
            new_url="https://novo.exemplo/url",
        )

        return type(
            "ResolveResultLike",
            (),
            {
                "success": True,
                "message": "Atualizado",
                "error_code": None,
                "product": updated_product,
                "match_result": type("MatchResultLike", (), {"score": 0.95})(),
            },
        )()


def test_monitor_service_detects_sku_change_and_runs(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir detecção de mudança de SKU/URL e execução completa do monitor.

    Parâmetros:
        tmp_path: Diretório temporário para arquivos de produtos/histórico.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre caminho de sucesso com emissão de eventos de alteração.
    """

    product_store = ProductStoreService(tmp_path / "products.json")
    history_store = HistoryStore(tmp_path / "history.json")

    product_store.upsert_product(
        ProductRecord(
            alias="item_ok",
            brand="Marca",
            name="Produto",
            variant="100ml",
            last_known_url="https://old.exemplo/item",
            last_known_sku="SKU-OLD",
        )
    )

    monitor_service = MonitorService(
        product_store=product_store,
        resolver=FakeResolverMonitor(product_store),
        history_store=history_store,
    )

    summary = monitor_service.run()

    assert summary.processed_count == 1
    assert summary.success_count == 1
    assert summary.error_count == 0

    stored_events = history_store.list_events_by_alias("item_ok")
    event_types = [event.event_type for event in stored_events]
    assert "sku_changed" in event_types
    assert "url_changed" in event_types


def test_monitor_service_registers_error_event(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar registro de evento de erro quando resolver falha.

    Parâmetros:
        tmp_path: Diretório temporário para arquivos de produtos/histórico.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante rastreabilidade de falhas operacionais no monitoramento.
    """

    product_store = ProductStoreService(tmp_path / "products.json")
    history_store = HistoryStore(tmp_path / "history.json")

    product_store.upsert_product(
        ProductRecord(
            alias="item_error",
            brand="Marca",
            name="Produto",
            variant="100ml",
            last_known_url="https://old.exemplo/error",
            last_known_sku="SKU-OLD",
        )
    )

    monitor_service = MonitorService(
        product_store=product_store,
        resolver=FakeResolverMonitor(product_store),
        history_store=history_store,
    )

    summary = monitor_service.run()

    assert summary.processed_count == 1
    assert summary.success_count == 0
    assert summary.error_count == 1

    events = history_store.list_events_by_alias("item_error")
    assert len(events) == 1
    assert events[0].event_type == "error"


def test_monitor_service_ignora_produtos_manuais_e_legados(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o monitor em lote processe apenas itens sincronizaveis.

    Parametros:
        tmp_path: Diretorio temporario para arquivos de produtos/historico.

    Retorno:
        Nenhum.

    Contexto de uso:
        Evita que perfumes internos ou fora do site aparecam como falha de
        sincronizacao quando o operador roda "Atualizar todos".
    """

    product_store = ProductStoreService(tmp_path / "products.json")
    history_store = HistoryStore(tmp_path / "history.json")

    product_store.upsert_product(
        ProductRecord(
            alias="item_site",
            brand="Marca",
            name="Produto Site",
            variant="100ml",
            last_known_url="https://old.exemplo/item-site",
            last_known_sku="SKU-SITE",
            source_type="site",
        )
    )
    product_store.upsert_product(
        ProductRecord(
            alias="item_manual",
            brand="Marca",
            name="Produto Manual",
            variant="100ml",
            last_known_url="",
            last_known_sku="SKU-MANUAL",
            source_type="manual",
        )
    )
    product_store.upsert_product(
        ProductRecord(
            alias="item_legacy",
            brand="Marca",
            name="Produto Legacy",
            variant="100ml",
            last_known_url="",
            last_known_sku="SKU-LEGACY",
            source_type="legacy",
        )
    )

    monitor_service = MonitorService(
        product_store=product_store,
        resolver=FakeResolverMonitor(product_store),
        history_store=history_store,
    )

    summary = monitor_service.run()

    assert summary.processed_count == 1
    assert summary.success_count == 1
    assert summary.error_count == 0
    assert history_store.list_events_by_alias("item_site")
    assert history_store.list_events_by_alias("item_manual") == []
    assert history_store.list_events_by_alias("item_legacy") == []


def test_monitor_service_resumo_expoe_alterados_sem_mudanca_e_ignorados(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o novo resumo do monitor diferencie os tipos de resultado.

    Parametros:
        tmp_path: Diretorio temporario para arquivos de produtos e historico.

    Retorno:
        Nenhum.

    Contexto de uso:
        A interface de progresso precisa separar alterados, sem mudanca e
        ignorados sem quebrar os contadores antigos do monitor.
    """

    product_store = ProductStoreService(tmp_path / "products.json")
    history_store = HistoryStore(tmp_path / "history.json")

    product_store.upsert_product(
        ProductRecord(
            alias="item_ok",
            brand="Marca",
            name="Produto Site",
            variant="100ml",
            last_known_url="https://old.exemplo/item-site",
            last_known_sku="SKU-SITE",
            source_type="site",
        )
    )
    product_store.upsert_product(
        ProductRecord(
            alias="item_manual",
            brand="Marca",
            name="Produto Manual",
            variant="100ml",
            last_known_url="",
            last_known_sku="SKU-MANUAL",
            source_type="manual",
        )
    )

    monitor_service = MonitorService(
        product_store=product_store,
        resolver=FakeResolverMonitor(product_store),
        history_store=history_store,
    )

    summary = monitor_service.run()

    assert summary.total_count == 1
    assert summary.processed_count == 1
    assert summary.updated_count == 1
    assert summary.unchanged_count == 0
    assert summary.failed_count == 0
    assert summary.skipped_count == 1


def test_monitor_service_pode_pular_item_muito_recente(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar o skip opcional de itens recentemente sincronizados.

    Parametros:
        tmp_path: Diretorio temporario para arquivos de produtos e historico.

    Retorno:
        Nenhum.

    Contexto de uso:
        O job em background pode rodar varias vezes em seguida, entao precisa
        conseguir pular itens frescos para ganhar desempenho sem retrabalho.
    """

    product_store = ProductStoreService(tmp_path / "products.json")
    history_store = HistoryStore(tmp_path / "history.json")

    product_store.upsert_product(
        ProductRecord(
            alias="item_recente",
            brand="Marca",
            name="Produto Recente",
            variant="100ml",
            last_known_url="https://old.exemplo/item-recente",
            last_known_sku="SKU-RECENTE",
            source_type="site",
            last_matched_at=get_current_utc_isoformat(),
        )
    )

    monitor_service = MonitorService(
        product_store=product_store,
        resolver=FakeResolverMonitor(product_store),
        history_store=history_store,
    )

    summary = monitor_service.run(skip_recent_seconds=300)

    assert summary.total_count == 0
    assert summary.processed_count == 0
    assert summary.skipped_count == 1
