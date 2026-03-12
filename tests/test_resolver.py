"""
Testes unitários da primeira versão do resolver de SKU.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from backend.utils.fetcher import FetchResult


class FakeFetcherSuccess:
    """
    Responsabilidade:
        Simular fetcher de sucesso com HTML controlado para testes.

    Parâmetros:
        html_content: HTML retornado em toda chamada de fetch.

    Retorno:
        Instância fake com método fetch_page compatível com o resolver.

    Contexto de uso:
        Isola testes do resolver sem depender de rede externa.
    """

    def __init__(self, html_content: str) -> None:
        """
        Responsabilidade:
            Guardar payload HTML estático para resposta fake.

        Parâmetros:
            html_content: Conteúdo HTML para retorno no fetch simulado.

        Retorno:
            Nenhum.

        Contexto de uso:
            Usado por testes para validar fluxo feliz e mismatch.
        """

        self.html_content = html_content

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Retornar resposta HTTP fake com URL e HTML predefinidos.

        Parâmetros:
            target_url: URL recebida do resolver para simulação do fetch.

        Retorno:
            FetchResult de sucesso com status 200.

        Contexto de uso:
            Substitui dependência de rede durante testes de unidade.
        """

        return FetchResult(final_url=target_url, status_code=200, html_content=self.html_content)


class FakeFetcherFailure:
    """
    Responsabilidade:
        Simular falha de rede durante etapa de fetch.

    Parâmetros:
        Nenhum.

    Retorno:
        Instância fake que lança exceção em fetch_page.

    Contexto de uso:
        Exercita tratamento de erro controlado no resolver.
    """

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Lançar erro de execução simulando indisponibilidade de rede.

        Parâmetros:
            target_url: URL alvo da tentativa de download.

        Retorno:
            Não retorna valor, pois sempre lança exceção.

        Contexto de uso:
            Garante cobertura do caminho de erro FETCH_FAILED.
        """

        raise RuntimeError(f"Falha simulada ao acessar {target_url}")


def _seed_product(store: ProductStoreService) -> None:
    """
    Responsabilidade:
        Inserir produto base no storage para os testes de resolução.

    Parâmetros:
        store: Serviço de armazenamento usado no cenário de teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Centraliza preparação de dado de entrada para evitar duplicações.
    """

    store.upsert_product(
        ProductRecord(
            alias="one_million_200ml",
            brand="Paco Rabanne",
            name="One Million",
            variant="200ml",
            last_known_url="https://loja.exemplo/produto",
            last_known_sku="old-000",
        )
    )


def test_resolver_success_with_valid_url(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar atualização de SKU quando página da URL conhecida faz match.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre fluxo principal da primeira versão do resolver.
    """

    html = """
    <html>
      <head>
        <title>One Million 200 ml</title>
        <meta property="product:brand" content="Paco Rabanne" />
        <meta property="og:title" content="One Million" />
      </head>
      <body>
        <div data-sku="NEW-123"></div>
      </body>
    </html>
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)
    resolver = ProductResolver(store, FakeFetcherSuccess(html))

    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is True
    assert result.product is not None
    assert result.product.last_known_sku == "NEW-123"


def test_resolver_returns_mismatch_when_identity_differs(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar que SKU não é atualizado quando a página não corresponde.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante regra principal de segurança da camada resolver.
    """

    html = """
    <html>
      <head>
        <title>Alien 90ml</title>
        <meta property="product:brand" content="Mugler" />
        <meta property="og:title" content="Alien" />
      </head>
      <body>
        <div data-sku="WRONG-999"></div>
      </body>
    </html>
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)
    resolver = ProductResolver(store, FakeFetcherSuccess(html))

    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is False
    assert result.error_code == "PRODUCT_MISMATCH"

    unchanged_product = store.get_by_alias("one_million_200ml")
    assert unchanged_product is not None
    assert unchanged_product.last_known_sku == "old-000"


def test_resolver_returns_fetch_failure(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar retorno controlado quando ocorre falha no fetch da página.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante rastreabilidade do erro sem quebrar fluxo de aplicação.
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)
    resolver = ProductResolver(store, FakeFetcherFailure())

    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is False
    assert result.error_code == "FETCH_FAILED"
