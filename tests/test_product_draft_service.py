"""
Testes do servico de rascunho automatico de produto a partir de URL.
"""

from __future__ import annotations

from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.product_draft_service import ProductDraftService
from backend.services.product_store_service import ProductStoreService
from backend.utils.fetcher import FetchResult


class FakeFetcher:
    """
    Responsabilidade:
        Simular leitura de HTML remoto para testes do servico de rascunho.

    Parametros:
        html_content: HTML devolvido sempre que `fetch_page` for chamado.

    Retorno:
        Instancia fake com o mesmo contrato do fetcher real.

    Contexto de uso:
        Mantem os testes sem rede e focados apenas na inferencia do cadastro.
    """

    def __init__(self, html_content: str) -> None:
        """
        Responsabilidade:
            Armazenar o HTML que sera usado nas respostas fake.

        Parametros:
            html_content: Documento HTML controlado pelo teste.

        Retorno:
            Nenhum.

        Contexto de uso:
            Setup simples para varios cenarios de parsing.
        """

        self.html_content = html_content

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Devolver HTML fake no formato esperado pelo servico.

        Parametros:
            target_url: URL enviada para o servico durante o teste.

        Retorno:
            FetchResult com URL final e HTML configurados.

        Contexto de uso:
            Substitui o cliente HTTP real na suite de testes unitarios.
        """

        return FetchResult(
            final_url=f"{target_url}/final",
            status_code=200,
            html_content=self.html_content,
        )


def test_product_draft_service_monta_rascunho_com_alias_limpo(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar montagem de rascunho legivel a partir dos metadados da pagina.

    Parametros:
        tmp_path: Diretorio temporario para o storage usado no teste.

    Retorno:
        Nenhum; valida sucesso e campos principais do rascunho.

    Contexto de uso:
        Garante o fluxo base do auto-preenchimento antes da camada web.
    """

    storage_service = ProductStoreService(tmp_path / "products.json")
    draft_service = ProductDraftService(
        fetcher=FakeFetcher(
            """
            <html>
              <head>
                <title>Aproveite: Paco Rabanne One Million com desconto especial - Renner</title>
                <meta property="product:brand" content="Paco Rabanne" />
                <meta property="og:title" content="Aproveite: Paco Rabanne One Million com desconto especial - Renner" />
                <meta name="description" content="Paco Rabanne One Million 200ml perfume masculino eau de toilette" />
                <meta property="og:image" content="/images/one-million.png" />
              </head>
              <body>
                <script type="application/ld+json">
                  {"sku": "546594103"}
                </script>
              </body>
            </html>
            """
        ),
        product_store=storage_service,
    )

    result = draft_service.build_from_url("https://example.com/produto")

    assert result.success is True
    assert result.draft is not None
    assert result.draft.brand == "Paco Rabanne"
    assert result.draft.name == "One Million"
    assert result.draft.variant == "200ml"
    assert result.draft.last_known_sku == "546594103"
    assert result.draft.alias == "paco_rabanne_one_million_200ml"


def test_product_draft_service_prioriza_descricao_em_vez_de_titulo_de_marketing(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o nome do rascunho prioriza descricao de produto real.

    Parametros:
        tmp_path: Diretorio temporario para o storage usado no teste.

    Retorno:
        Nenhum; valida apenas a heuristica do campo `name`.

    Contexto de uso:
        Protege o auto-preenchimento contra titulos promocionais de vitrine.
    """

    storage_service = ProductStoreService(tmp_path / "products.json")
    draft_service = ProductDraftService(
        fetcher=FakeFetcher(
            """
            <html>
              <head>
                <title>Compre online agora com desconto - Renner</title>
                <meta property="product:brand" content="Carolina Herrera" />
                <meta property="og:title" content="Oferta imperdivel Carolina Herrera Good Girl - Renner" />
                <meta name="description" content="Carolina Herrera Good Girl 80ml perfume feminino eau de parfum" />
              </head>
              <body>
                SKU: 123456
              </body>
            </html>
            """
        ),
        product_store=storage_service,
    )

    result = draft_service.build_from_url("https://example.com/produto")

    assert result.success is True
    assert result.draft is not None
    assert result.draft.name == "Good Girl"
    assert result.draft.variant == "80ml"


def test_product_draft_service_incrementa_alias_quando_ja_existe(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir sufixo numerico quando o alias sugerido ja estiver ocupado.

    Parametros:
        tmp_path: Diretorio temporario do storage de produtos.

    Retorno:
        Nenhum; valida apenas a regra de unicidade do alias.

    Contexto de uso:
        Evita colisao silenciosa ao cadastrar produtos parecidos pela mesma URL.
    """

    storage_service = ProductStoreService(tmp_path / "products.json")
    storage_service.upsert_product(
        ProductRecord(
            alias="paco_rabanne_one_million_200ml",
            brand="Paco Rabanne",
            name="One Million",
            variant="200ml",
            last_known_url="https://example.com/existente",
            last_known_sku="111",
        )
    )
    draft_service = ProductDraftService(
        fetcher=FakeFetcher(
            """
            <html>
              <head>
                <title>Paco Rabanne One Million 200ml - Renner</title>
                <meta property="product:brand" content="Paco Rabanne" />
                <meta property="og:title" content="Paco Rabanne One Million 200ml - Renner" />
              </head>
              <body>
                SKU: 546594103
              </body>
            </html>
            """
        ),
        product_store=storage_service,
    )

    result = draft_service.build_from_url("https://example.com/produto")

    assert result.success is True
    assert result.draft is not None
    assert result.draft.alias == "paco_rabanne_one_million_200ml_2"


def test_product_draft_service_reduz_nome_de_marketing_e_alias_gigante(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o auto-preenchimento enxugue textos promocionais longos.

    Parametros:
        tmp_path: Diretorio temporario do storage de produtos.

    Retorno:
        Nenhum; valida nome operacional e alias em tamanho razoavel.

    Contexto de uso:
        Protege o fluxo de cadastro por URL contra paginas com SEO exagerado,
        evitando nomes de marketing e aliases grandes demais para manutencao.
    """

    storage_service = ProductStoreService(tmp_path / "products.json")
    draft_service = ProductDraftService(
        fetcher=FakeFetcher(
            """
            <html>
              <head>
                <title>Oferta exclusiva: Jean Paul Gaultier Le Beau Le Parfum com desconto especial e frete gratis - Renner</title>
                <meta property="product:brand" content="Jean Paul Gaultier" />
                <meta property="og:title" content="Compre online Jean Paul Gaultier Le Beau Le Parfum 125ml importado original masculino - Renner" />
                <meta name="description" content="Jean Paul Gaultier Le Beau Le Parfum 125ml perfume masculino eau de parfum importado original" />
              </head>
              <body>
                SKU: 998877
              </body>
            </html>
            """
        ),
        product_store=storage_service,
    )

    result = draft_service.build_from_url("https://example.com/produto")

    assert result.success is True
    assert result.draft is not None
    assert result.draft.name == "Le Beau Le Parfum"
    assert result.draft.variant == "125ml"
    assert result.draft.alias == "jean_paul_le_beau_le_parfum_125ml"
    assert len(result.draft.alias) <= 48
