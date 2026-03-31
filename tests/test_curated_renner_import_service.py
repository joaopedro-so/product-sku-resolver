"""
Testes do servico de importacao curada de produtos da Renner.
"""

import json
from pathlib import Path

from backend.services.curated_renner_import_service import (
    CuratedRennerImportEntry,
    CuratedRennerImportService,
)
from backend.services.product_store_service import ProductStoreService
from backend.utils.fetcher import FetchResult


class FakeFetcher:
    """
    Responsabilidade:
        Simular respostas HTTP da Renner sem depender de rede nos testes.

    Parametros:
        responses_by_url: Mapa entre URL consultada e resultado esperado.

    Retorno:
        Instancia simples com a mesma interface minima do Fetcher real.

    Contexto de uso:
        Permite validar a logica do importador com HTML controlado e
        deterministico, evitando flutuações externas no ambiente de CI.
    """

    def __init__(self, responses_by_url: dict[str, FetchResult]) -> None:
        """
        Responsabilidade:
            Guardar o catalogo de respostas fake usado pelo teste.

        Parametros:
            responses_by_url: Dicionario indexado pela URL do fetch esperado.

        Retorno:
            Nenhum.

        Contexto de uso:
            Chamado localmente em cada teste para isolar os cenarios.
        """

        self.responses_by_url = responses_by_url

    def fetch_page(self, target_url: str, extra_headers: dict[str, str] | None = None) -> FetchResult:
        """
        Responsabilidade:
            Retornar uma resposta fake para a URL solicitada pelo importador.

        Parametros:
            target_url: URL consultada durante a validacao da importacao.
            extra_headers: Cabecalhos extras ignorados neste fake.

        Retorno:
            FetchResult configurado pelo proprio teste.

        Contexto de uso:
            Imita apenas o contrato usado pelo servico real, mantendo o fake
            pequeno e didatico sem reproduzir toda a implementacao de rede.
        """

        if target_url not in self.responses_by_url:
            raise AssertionError(f"URL nao prevista no teste: {target_url}")
        return self.responses_by_url[target_url]


def _build_valid_product_html(page_title: str, sku: str) -> str:
    """
    Responsabilidade:
        Montar um HTML minimo com titulo e SKU confirmados para o teste.

    Parametros:
        page_title: Titulo que a pagina fake deve expor no elemento `<title>`.
        sku: SKU que precisa aparecer no HTML para a validacao passar.

    Retorno:
        Documento HTML simplificado, suficiente para o parser atual.

    Contexto de uso:
        Ajuda a manter os testes curtos, reaproveitando um mesmo formato base.
    """

    return (
        "<html><head>"
        f"<title>{page_title}</title>"
        f"<meta property=\"og:title\" content=\"{page_title}\"/>"
        "</head><body>"
        f"<input type=\"radio\" data-name=\"100ml\" data-sku=\"{sku}\" />"
        "</body></html>"
    )


def test_curated_renner_import_service_persiste_produto_curado_no_storage(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que uma entrada curada valida seja persistida no JSON final.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest para isolamento.

    Retorno:
        Nenhum; valida o produto persistido no storage temporario.

    Contexto de uso:
        Protege o fluxo principal do importador que a operacao usara para
        cadastrar perfumes reais a partir de seeds revisados manualmente.
    """

    storage_file_path = tmp_path / "products.json"
    product_store = ProductStoreService(storage_file_path=storage_file_path)
    page_url = "https://www.lojasrenner.com.br/p/perfume-x/-/A-123-br.lr"
    entry = CuratedRennerImportEntry(
        alias="marca_perfume_x_100ml",
        brand="Marca",
        name="Perfume X",
        variant="100ml",
        sku="123456",
        page_url=page_url,
        shelf_number=3,
        display_order=9,
        expected_title_fragment="perfume x",
    )
    import_service = CuratedRennerImportService(
        fetcher=FakeFetcher(
            {
                page_url: FetchResult(
                    final_url=page_url,
                    status_code=200,
                    html_content=_build_valid_product_html("Perfume X 100ml - Lojas Renner", "123456"),
                )
            }
        ),
        product_store=product_store,
    )

    result = import_service.import_single_entry(entry)

    assert result.success is True
    persisted_product = product_store.get_by_alias("marca_perfume_x_100ml")
    assert persisted_product is not None
    assert persisted_product.brand == "Marca"
    assert persisted_product.name == "Perfume X"
    assert persisted_product.variant == "100ml"
    assert persisted_product.last_known_sku == "123456"
    assert persisted_product.last_known_url == f"{page_url}?sku=123456"
    assert persisted_product.shelf_number == 3
    assert persisted_product.display_order == 9


def test_curated_renner_import_service_falha_quando_sku_nao_aparece_na_pagina(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir erro explicito quando a curadoria aponta SKU para pagina errada.

    Parametros:
        tmp_path: Diretorio temporario usado para storage isolado do teste.

    Retorno:
        Nenhum; valida a falha e a ausencia de persistencia indevida.

    Contexto de uso:
        Evita importar lixo operacional quando a lista manual tiver typo ou
        quando a pagina da Renner nao confirmar o SKU esperado.
    """

    storage_file_path = tmp_path / "products.json"
    product_store = ProductStoreService(storage_file_path=storage_file_path)
    page_url = "https://www.lojasrenner.com.br/p/perfume-y/-/A-456-br.lr"
    entry = CuratedRennerImportEntry(
        alias="marca_perfume_y_50ml",
        brand="Marca",
        name="Perfume Y",
        variant="50ml",
        sku="999999",
        page_url=page_url,
        shelf_number=2,
    )
    import_service = CuratedRennerImportService(
        fetcher=FakeFetcher(
            {
                page_url: FetchResult(
                    final_url=page_url,
                    status_code=200,
                    html_content=_build_valid_product_html("Perfume Y 50ml - Lojas Renner", "111111"),
                )
            }
        ),
        product_store=product_store,
    )

    result = import_service.import_single_entry(entry)

    assert result.success is False
    assert "nao foi confirmado" in result.message.lower()
    assert product_store.list_products() == []


def test_curated_renner_import_service_carrega_seed_json(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o seed JSON seja convertido corretamente em entradas tipadas.

    Parametros:
        tmp_path: Diretorio temporario onde o arquivo de seed sera criado.

    Retorno:
        Nenhum; valida leitura do arquivo e normalizacao dos campos.

    Contexto de uso:
        Protege o contrato do seed curado para que scripts internos consigam
        reaproveitar a mesma estrutura com seguranca.
    """

    seed_file_path = tmp_path / "seed.json"
    seed_file_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "alias": "produto_teste_30ml",
                        "brand": "Marca Teste",
                        "name": "Produto Teste",
                        "variant": "30ml",
                        "sku": "321654",
                        "page_url": "https://www.lojasrenner.com.br/p/produto-teste/-/A-789-br.lr",
                        "shelf_number": 1,
                        "display_order": 4,
                        "expected_title_fragment": "produto teste",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    import_service = CuratedRennerImportService(
        fetcher=FakeFetcher({}),
        product_store=ProductStoreService(storage_file_path=tmp_path / "products.json"),
    )

    entries = import_service.load_entries_from_file(seed_file_path)

    assert len(entries) == 1
    assert entries[0].alias == "produto_teste_30ml"
    assert entries[0].brand == "Marca Teste"
    assert entries[0].display_order == 4
