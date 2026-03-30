"""
Testes da camada de rotas da API sem dependência de cliente HTTP externo.
"""

from pathlib import Path
from types import SimpleNamespace

from api.routes_products import (
    create_product,
    get_product,
    healthcheck,
    list_history,
    list_history_by_alias,
    list_products,
    run_monitor,
    update_all_products,
    update_product,
)
from api.schemas import ProductCreate
from backend.models.sku_event import SkuEvent
from backend.services.runtime_context import RuntimeServices
from history.history_store import HistoryStore


class FakeResolver:
    """
    Responsabilidade:
        Simular resolver para validação dos endpoints em testes unitários.

    Parâmetros:
        store: Serviço de storage para atualização fake do produto.

    Retorno:
        Instância com assinatura compatível à usada pelas rotas.

    Contexto de uso:
        Evita chamadas externas e mantém foco no contrato das rotas.
    """

    def __init__(self, store) -> None:
        """
        Responsabilidade:
            Guardar referência ao store para simulação de atualização.

        Parâmetros:
            store: ProductStoreService compartilhado no cenário de teste.

        Retorno:
            Nenhum.

        Contexto de uso:
            Setup do fake resolver utilizado pelas rotas.
        """

        self.store = store

    def resolve_sku_for_alias(self, product_alias: str):
        """
        Responsabilidade:
            Simular resolução de SKU por alias para testes das rotas.

        Parâmetros:
            product_alias: Alias do produto alvo da atualização.

        Retorno:
            Objeto similar ao ResolveResult esperado pelas rotas.

        Contexto de uso:
            Permite validar serialização de UpdateResult sem rede.
        """

        product = self.store.get_by_alias(product_alias)
        if product is None:
            return type(
                "ResolveResultLike",
                (),
                {
                    "success": False,
                    "message": "Produto não encontrado",
                    "error_code": "PRODUCT_NOT_FOUND",
                    "product": None,
                },
            )()

        updated_product = self.store.update_product_sku_and_url(product_alias, "SKU-NEW", "https://novo.exemplo/item")
        return type(
            "ResolveResultLike",
            (),
            {
                "success": True,
                "message": "Atualizado com sucesso",
                "error_code": None,
                "product": updated_product,
            },
        )()


class FakeMonitorService:
    """
    Responsabilidade:
        Simular monitor_service para endpoint de execução manual.

    Parâmetros:
        history_store: Store de histórico onde eventos serão registrados.

    Retorno:
        Instância fake com método run compatível ao monitor real.

    Contexto de uso:
        Valida contrato do endpoint /monitor/run e histórico da API.
    """

    def __init__(self, history_store: HistoryStore) -> None:
        """
        Responsabilidade:
            Armazenar referência ao histórico para emissão de eventos fake.

        Parâmetros:
            history_store: Serviço de histórico compartilhado no teste.

        Retorno:
            Nenhum.

        Contexto de uso:
            Setup do monitor fake para as rotas de monitoramento.
        """

        self.history_store = history_store

    def run(self):
        """
        Responsabilidade:
            Simular uma execução de monitoramento com evento emitido.

        Parâmetros:
            Nenhum.

        Retorno:
            Objeto similar ao MonitorRunSummary consumido pela rota.

        Contexto de uso:
            Exercita serialização do endpoint POST /monitor/run.
        """

        emitted_event = SkuEvent.create(
            alias="item_1",
            event_type="sku_changed",
            old_sku="SKU-OLD",
            new_sku="SKU-NEW",
            old_url="https://old/item",
            new_url="https://new/item",
            match_score=0.9,
        )
        self.history_store.save_event(emitted_event)
        return type(
            "MonitorRunSummaryLike",
            (),
            {
                "processed_count": 1,
                "success_count": 1,
                "error_count": 0,
                "emitted_events": [emitted_event],
            },
        )()


def _build_request(tmp_path: Path):
    """
    Responsabilidade:
        Criar objeto request simplificado com services em app.state.

    Parâmetros:
        tmp_path: Diretório temporário para storage isolado.

    Retorno:
        Estrutura similar ao Request com estado de aplicação configurado.

    Contexto de uso:
        Suporte aos testes unitários das funções de rota.
    """

    from backend.services.product_store_service import ProductStoreService

    product_store = ProductStoreService(tmp_path / "products.json")
    history_store = HistoryStore(tmp_path / "history.json")
    services = RuntimeServices(
        product_store=product_store,
        resolver=FakeResolver(product_store),
        history_store=history_store,
        monitor_service=FakeMonitorService(history_store),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=services)))


def test_health_endpoint() -> None:
    """
    Responsabilidade:
        Validar contrato mínimo do endpoint de saúde da API.

    Parâmetros:
        Nenhum.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante sinal básico de disponibilidade das rotas.
    """

    assert healthcheck() == {"status": "ok"}


def test_products_routes_flow(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Cobrir fluxo principal de cadastro, consulta e update individual.

    Parâmetros:
        tmp_path: Diretório temporário para isolamento dos arquivos de teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Valida endpoints centrais da operação de produtos.
    """

    request = _build_request(tmp_path)

    created = create_product(
        ProductCreate(
            alias="item_1",
            brand="Marca",
            name="Produto",
            variant="100ml",
            last_known_url="https://old.exemplo/item",
            last_known_sku="SKU-OLD",
        ),
        request,
    )
    assert created.alias == "item_1"

    all_products = list_products(request)
    assert len(all_products) == 1

    found = get_product("item_1", request)
    assert found.alias == "item_1"

    updated = update_product("item_1", request)
    assert updated.success is True
    assert updated.updated_sku == "SKU-NEW"


def test_update_all_and_history_routes(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar atualização em lote e consulta de histórico da API.

    Parâmetros:
        tmp_path: Diretório temporário para isolamento dos arquivos de teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre endpoints novos de monitoramento e auditoria.
    """

    request = _build_request(tmp_path)

    for alias in ["item_a", "item_b"]:
        create_product(
            ProductCreate(
                alias=alias,
                brand="Marca",
                name="Produto",
                variant="100ml",
                last_known_url="https://old.exemplo/item",
                last_known_sku="SKU-OLD",
            ),
            request,
        )

    batch_results = update_all_products(request)
    assert len(batch_results) == 2

    monitor_response = run_monitor(request)
    assert monitor_response.processed_count == 1
    assert monitor_response.emitted_events == 1

    all_history = list_history(request)
    alias_history = list_history_by_alias("item_1", request)

    assert len(all_history) >= 1
    assert len(alias_history) >= 1
