"""
Testes unitários da CLI operacional do projeto.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.models.sku_event import SkuEvent
from backend.services.runtime_context import RuntimeServices
from cli.cli import run_cli
from history.history_store import HistoryStore


class FakeResolverForCli:
    """
    Responsabilidade:
        Simular resolver para testes de comandos CLI sem acesso à rede.

    Parâmetros:
        store: Serviço de armazenamento para atualização fake de produtos.

    Retorno:
        Instância com método resolve_sku_for_alias usado pela CLI.

    Contexto de uso:
        Permite validar fluxo dos comandos update e update-all.
    """

    def __init__(self, store) -> None:
        """
        Responsabilidade:
            Guardar serviço de storage para atualização fake em testes.

        Parâmetros:
            store: ProductStoreService compartilhado com os comandos.

        Retorno:
            Nenhum.

        Contexto de uso:
            Inicialização do fake resolver em ambiente de teste.
        """

        self.store = store

    def resolve_sku_for_alias(self, product_alias: str):
        """
        Responsabilidade:
            Simular atualização de SKU para alias existente.

        Parâmetros:
            product_alias: Alias alvo da tentativa de update.

        Retorno:
            Objeto com interface mínima esperada pela CLI.

        Contexto de uso:
            Substitui resolver real para asserts determinísticos.
        """

        found_product = self.store.get_by_alias(product_alias)
        if found_product is None:
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

        updated = self.store.update_product_sku_and_url(product_alias, "SKU-CLI", "https://cli.exemplo/novo")
        return type(
            "ResolveResultLike",
            (),
            {
                "success": True,
                "message": "Atualizado via CLI",
                "error_code": None,
                "product": updated,
            },
        )()


class FakeMonitorServiceForCli:
    """
    Responsabilidade:
        Simular monitor_service para testes dos comandos monitor/history.

    Parâmetros:
        history_store: Store onde eventos serão gravados pelo monitor fake.

    Retorno:
        Instância fake com método run compatível com CLI.

    Contexto de uso:
        Garante previsibilidade para asserts dos novos comandos.
    """

    def __init__(self, history_store: HistoryStore) -> None:
        """
        Responsabilidade:
            Inicializar fake monitor com acesso ao histórico de eventos.

        Parâmetros:
            history_store: Serviço de persistência de histórico.

        Retorno:
            Nenhum.

        Contexto de uso:
            Setup de testes dos comandos monitor e history.
        """

        self.history_store = history_store

    def run(self):
        """
        Responsabilidade:
            Simular execução de monitoramento com emissão de um evento.

        Parâmetros:
            Nenhum.

        Retorno:
            Objeto simples compatível com MonitorRunSummary.

        Contexto de uso:
            Suporte aos testes do comando `python -m cli monitor`.
        """

        event = SkuEvent.create(
            alias="item_a",
            event_type="sku_changed",
            old_sku="SKU-A",
            new_sku="SKU-CLI",
            old_url="https://old/a",
            new_url="https://cli.exemplo/novo",
            match_score=0.92,
        )
        self.history_store.save_event(event)
        return type(
            "MonitorRunSummaryLike",
            (),
            {
                "processed_count": 1,
                "success_count": 1,
                "error_count": 0,
                "emitted_events": [event],
            },
        )()


def _build_services(storage_path: Path) -> RuntimeServices:
    """
    Responsabilidade:
        Construir serviços de teste reutilizados pelos cenários da CLI.

    Parâmetros:
        storage_path: Caminho do arquivo JSON isolado por teste.

    Retorno:
        RuntimeServices contendo stores e fakes de resolução/monitoramento.

    Contexto de uso:
        Evita repetição de setup entre funções de teste de comando.
    """

    from backend.services.product_store_service import ProductStoreService

    product_store = ProductStoreService(storage_path)
    history_store = HistoryStore(storage_path.parent / "history.json")
    return RuntimeServices(
        product_store=product_store,
        resolver=FakeResolverForCli(product_store),
        history_store=history_store,
        monitor_service=FakeMonitorServiceForCli(history_store),
    )


def test_cli_add_and_list_commands(tmp_path: Path, capsys) -> None:
    """
    Responsabilidade:
        Validar comandos de cadastro e listagem na interface de terminal.

    Parâmetros:
        tmp_path: Diretório temporário para storage isolado.
        capsys: Capturador de stdout/stderr do pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre operações básicas de gerenciamento local de catálogo.
    """

    services = _build_services(tmp_path / "products.json")

    add_exit_code = run_cli(
        [
            "add",
            "--alias",
            "item_cli",
            "--brand",
            "Marca",
            "--name",
            "Produto",
            "--variant",
            "100ml",
            "--url",
            "https://url.antiga/produto",
            "--sku",
            "SKU-OLD",
        ],
        services=services,
    )
    list_exit_code = run_cli(["list"], services=services)
    captured = capsys.readouterr()

    assert add_exit_code == 0
    assert list_exit_code == 0
    assert "Produto salvo com sucesso" in captured.out
    assert "Total de produtos: 1" in captured.out


def test_cli_update_monitor_and_history_commands(tmp_path: Path, capsys) -> None:
    """
    Responsabilidade:
        Validar comandos de atualização, monitoramento e consulta de histórico.

    Parâmetros:
        tmp_path: Diretório temporário para storage isolado.
        capsys: Capturador de saída padrão para asserts de mensagens.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre novos comandos monitor, history e history-all da CLI.
    """

    services = _build_services(tmp_path / "products.json")
    services.product_store.upsert_product(
        ProductRecord(
            alias="item_a",
            brand="Marca",
            name="Produto",
            variant="100ml",
            last_known_url="https://url.antiga/a",
            last_known_sku="SKU-A",
        )
    )

    update_exit_code = run_cli(["update", "item_a"], services=services)
    monitor_exit_code = run_cli(["monitor"], services=services)
    history_alias_exit_code = run_cli(["history", "item_a"], services=services)
    history_all_exit_code = run_cli(["history-all"], services=services)
    captured = capsys.readouterr()

    assert update_exit_code == 0
    assert monitor_exit_code == 0
    assert history_alias_exit_code == 0
    assert history_all_exit_code == 0
    assert "Atualizado via CLI" in captured.out
    assert "Monitor executado" in captured.out
    assert "Total de eventos" in captured.out
