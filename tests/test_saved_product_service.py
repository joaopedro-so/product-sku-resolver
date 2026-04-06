"""
Testes da camada de acesso rapido persistido.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.services.saved_product_service import SavedProductService


def test_saved_product_service_aceita_formato_legado_baseado_em_aliases(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir compatibilidade com o formato antigo de lista simples.

    Parametros:
        tmp_path: Diretorio temporario usado para isolar o arquivo do teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege os ambientes que ja possuem `saved_products.json` gravado como
        lista de strings e nao devem perder os atalhos apos o refactor.
    """

    storage_file_path = tmp_path / "saved_products.json"
    storage_file_path.write_text(
        json.dumps(["produto_a", "produto_b"], ensure_ascii=False),
        encoding="utf-8",
    )

    service = SavedProductService(storage_file_path)

    entries = service.list_entries()

    assert [entry.alias for entry in entries] == ["produto_a", "produto_b"]
    assert entries[0].tag == "quick_access"
    assert service.is_saved("produto_b") is True


def test_saved_product_service_persiste_tag_e_timestamp_no_formato_novo(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o acesso rapido grave metadados uteis para evolucao futura.

    Parametros:
        tmp_path: Diretorio temporario usado para isolar o arquivo do teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Mantem o storage pronto para distinguir itens de campanha,
        monitoramento e acesso rapido padrao sem quebrar o contrato atual.
    """

    storage_file_path = tmp_path / "saved_products.json"
    service = SavedProductService(storage_file_path)

    service.save_alias("produto_campanha", tag="campaign")

    persisted_payload = json.loads(storage_file_path.read_text(encoding="utf-8"))

    assert persisted_payload[0]["alias"] == "produto_campanha"
    assert persisted_payload[0]["tag"] == "campaign"
    assert persisted_payload[0]["saved_at"]
    assert service.count_by_tag() == {"campaign": 1}
