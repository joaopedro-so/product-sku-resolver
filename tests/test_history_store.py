"""
Testes unitários da camada de persistência de histórico de eventos.
"""

from pathlib import Path

from backend.models.sku_event import SkuEvent
from history.history_store import HistoryStore


def test_history_store_registers_and_lists_events(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que eventos sejam persistidos e listados corretamente.

    Parâmetros:
        tmp_path: Diretório temporário para arquivo JSON de histórico.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre fluxo principal de registro e leitura no HistoryStore.
    """

    store = HistoryStore(tmp_path / "history.json")

    first_event = SkuEvent.create(
        alias="item_a",
        event_type="sku_changed",
        old_sku="OLD-1",
        new_sku="NEW-1",
        old_url="https://old/a",
        new_url="https://new/a",
        match_score=1.0,
    )
    store.save_event(first_event)

    all_events = store.list_events()
    assert len(all_events) == 1
    assert all_events[0].alias == "item_a"
    assert all_events[0].event_type == "sku_changed"


def test_history_store_filters_by_alias(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar filtro de histórico por alias de produto específico.

    Parâmetros:
        tmp_path: Diretório temporário para arquivo JSON de histórico.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante comportamento esperado para consulta pontual de auditoria.
    """

    store = HistoryStore(tmp_path / "history.json")
    store.save_event(
        SkuEvent.create(
            alias="item_a",
            event_type="sku_changed",
            old_sku="A1",
            new_sku="A2",
            old_url="https://old/a",
            new_url="https://new/a",
            match_score=0.9,
        )
    )
    store.save_event(
        SkuEvent.create(
            alias="item_b",
            event_type="error",
            old_sku="B1",
            new_sku="B1",
            old_url="https://old/b",
            new_url="https://old/b",
            match_score=None,
        )
    )

    alias_events = store.list_events_by_alias("item_a")
    assert len(alias_events) == 1
    assert alias_events[0].alias == "item_a"
