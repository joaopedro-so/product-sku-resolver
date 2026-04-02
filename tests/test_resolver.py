"""
Testes unitários do resolver com fallback de descoberta automática de URL.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.models.search_result import SearchResult
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from backend.utils.fetcher import FetchResult


class FakeFetcherMap:
    """
    Responsabilidade:
        Simular fetcher com respostas diferentes por URL para cenários complexos.

    Parâmetros:
        html_by_url: Mapa URL -> HTML usado para resposta de cada fetch.

    Retorno:
        Instância fake com contrato compatível ao Fetcher real.

    Contexto de uso:
        Permite testar resolver com múltiplos candidatos sem rede externa.
    """

    def __init__(self, html_by_url: dict[str, str]) -> None:
        """
        Responsabilidade:
            Armazenar tabela de respostas simuladas por URL.

        Parâmetros:
            html_by_url: Conteúdo HTML esperado para cada URL de teste.

        Retorno:
            Nenhum.

        Contexto de uso:
            Preparação de fixture fake para testes do resolver.
        """

        self.html_by_url = html_by_url

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Retornar HTML da URL solicitada ou erro quando não mapeada.

        Parâmetros:
            target_url: URL alvo recebida no fluxo do resolver.

        Retorno:
            FetchResult com status 200 quando URL estiver configurada.

        Contexto de uso:
            Simula respostas diferentes para last_known_url e candidatos.
        """

        if target_url not in self.html_by_url:
            raise RuntimeError(f"URL não mapeada no fake fetcher: {target_url}")

        return FetchResult(final_url=target_url, status_code=200, html_content=self.html_by_url[target_url])


class FakeFetcherFailure:
    """
    Responsabilidade:
        Simular falha total de rede durante etapa de fetch.

    Parâmetros:
        Nenhum.

    Retorno:
        Instância fake que lança exceção em qualquer chamada.

    Contexto de uso:
        Valida tratamento de erro controlado no caminho sem fallback útil.
    """

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Lançar erro simulando indisponibilidade no download da página.

        Parâmetros:
            target_url: URL recebida, usada apenas para compor mensagem.

        Retorno:
            Não retorna valor, pois sempre levanta exceção.

        Contexto de uso:
            Exercita regra de robustez da camada resolver.
        """

        raise RuntimeError(f"Falha simulada ao acessar {target_url}")


class FakeFetcherTimeout:
    """
    Responsabilidade:
        Simular timeout de rede durante etapa de fetch da página.

    Parâmetros:
        Nenhum.

    Retorno:
        Instância fake que sempre falha com mensagem de timeout.

    Contexto de uso:
        Garante que o resolver converta lentidão externa em erro controlado.
    """

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Lançar erro simulando expiração de tempo da requisição HTTP.

        Parâmetros:
            target_url: URL recebida, usada apenas na composição do erro.

        Retorno:
            Não retorna valor, pois sempre lança exceção.

        Contexto de uso:
            Exercita caminho de timeout tratado pelo resolver.
        """

        raise RuntimeError(f"Timeout ao buscar URL após 8s: {target_url}")


class FakeSearchProvider:
    """
    Responsabilidade:
        Simular provider de busca retornando candidatos determinísticos.

    Parâmetros:
        results: Lista de SearchResult que será retornada em search.

    Retorno:
        Instância fake para teste de fallback sem chamadas externas.

    Contexto de uso:
        Usada para validar escolha de melhor candidato pelo resolver.
    """

    def __init__(self, results: list[SearchResult]) -> None:
        """
        Responsabilidade:
            Guardar resultados estáticos para uso durante os testes.

        Parâmetros:
            results: Lista de candidatos em ordem de relevância simulada.

        Retorno:
            Nenhum.

        Contexto de uso:
            Fixture fake para cenários de fallback de busca.
        """

        self.results = results

    def search(self, product_record: ProductRecord) -> list[SearchResult]:
        """
        Responsabilidade:
            Retornar candidatos de busca pré-configurados pelo teste.

        Parâmetros:
            product_record: Produto alvo (não utilizado na versão fake).

        Retorno:
            Lista estática de SearchResult definida no construtor.

        Contexto de uso:
            Substitui provider real para foco na lógica de resolução.
        """

        return self.results


def _seed_product(store: ProductStoreService) -> None:
    """
    Responsabilidade:
        Inserir produto base no storage para cenários de resolução.

    Parâmetros:
        store: Serviço de armazenamento usado no teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Evita duplicação de dados de entrada entre casos de teste.
    """

    store.upsert_product(
        ProductRecord(
            alias="one_million_200ml",
            brand="Paco Rabanne",
            name="One Million",
            variant="200ml",
            last_known_url="https://loja.exemplo/produto-antigo",
            last_known_sku="old-000",
        )
    )


def test_resolver_success_with_valid_url(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar atualização de SKU quando last_known_url ainda funciona.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre caminho feliz sem necessidade de fallback de busca.
    """

    html_valid = """
    <html><head>
      <title>One Million 200 ml</title>
      <meta property="product:brand" content="Paco Rabanne" />
      <meta property="og:title" content="One Million" />
    </head><body><div data-sku="NEW-123"></div></body></html>
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)

    fetcher = FakeFetcherMap({"https://loja.exemplo/produto-antigo": html_valid})
    resolver = ProductResolver(store, fetcher)

    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is True
    assert result.product is not None
    assert result.product.last_known_sku == "NEW-123"


def test_resolver_accepts_kit_page_with_generic_title_when_code_matches(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir sync de kit quando a página mantém o código, mas simplifica o nome.

    Parâmetros:
        tmp_path: Diretório temporário para storage isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reproduz o caso do kit Adidas UEFA Goal na Ashua, que hoje existe no
        site com o mesmo código operacional, mas um título menos específico.
    """

    html_valid = """
    <html><head>
      <title>Kit Adidas Uefa Eau de Toilette 50ml + Gel de Banho 250ml KIT</title>
      <meta property="og:title" content="Kit Adidas Uefa Eau de Toilette 50ml + Gel de Banho 250ml KIT - Lojas Renner" />
    </head><body><div data-sku="929705341"></div></body></html>
    """

    store = ProductStoreService(tmp_path / "products.json")
    store.upsert_product(
        ProductRecord(
            alias="adidas_uefa_goal_kit_50ml_gel_banho_250ml",
            brand="Adidas",
            name="Kit Adidas UEFA Goal + Gel de Banho",
            variant="KIT",
            last_known_url="https://www.lojasrenner.com.br/ashua/p/kit-adidas-uefa-eau-de-toilette-50ml-gel-de-banho-250ml/-/A-929705333-br.lr?sku=929705341",
            last_known_sku="929705341",
            concentration="KIT",
        )
    )

    fetcher = FakeFetcherMap(
        {
            "https://www.lojasrenner.com.br/ashua/p/kit-adidas-uefa-eau-de-toilette-50ml-gel-de-banho-250ml/-/A-929705333-br.lr?sku=929705341": html_valid
        }
    )
    resolver = ProductResolver(store, fetcher)

    result = resolver.resolve_sku_for_alias("adidas_uefa_goal_kit_50ml_gel_banho_250ml")

    assert result.success is True
    assert result.match_result is not None
    assert result.match_result.matched is True
    assert result.product is not None
    assert result.product.last_known_sku == "929705341"


def test_resolver_chooses_best_search_candidate(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que resolver escolhe candidato com maior score validado.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Cobre regra central de priorização no fallback de busca.
    """

    html_mismatch = """
    <html><head>
      <title>Alien 90ml</title>
      <meta property="product:brand" content="Mugler" />
      <meta property="og:title" content="Alien" />
    </head><body><div data-sku="WRONG-001"></div></body></html>
    """

    html_score_08 = """
    <html><head>
      <title>Paco Rabanne One Million</title>
      <meta property="product:brand" content="Paco Rabanne" />
      <meta property="og:title" content="One Million" />
    </head><body><div data-sku="SKU-800"></div></body></html>
    """

    html_score_10 = """
    <html><head>
      <title>One Million 200 ml</title>
      <meta property="product:brand" content="Paco Rabanne" />
      <meta property="og:title" content="One Million 200ml" />
    </head><body><div data-sku="SKU-1000"></div></body></html>
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)

    fetcher = FakeFetcherMap(
        {
            "https://loja.exemplo/produto-antigo": html_mismatch,
            "https://lojasrenner.com.br/p/perfume-one-million": html_score_08,
            "https://lojasrenner.com.br/p/perfume-one-million-200ml": html_score_10,
        }
    )
    provider = FakeSearchProvider(
        [
            SearchResult(
                url="https://lojasrenner.com.br/p/perfume-one-million",
                title="One Million",
                source="fake",
            ),
            SearchResult(
                url="https://lojasrenner.com.br/p/perfume-one-million-200ml",
                title="One Million 200ml",
                source="fake",
            ),
        ]
    )

    resolver = ProductResolver(store, fetcher, search_provider=provider, search_match_threshold=0.75)
    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is True
    assert result.match_result is not None
    assert result.match_result.score == 1.0

    updated = store.get_by_alias("one_million_200ml")
    assert updated is not None
    assert updated.last_known_sku == "SKU-1000"
    assert updated.last_known_url == "https://lojasrenner.com.br/p/perfume-one-million-200ml"


def test_resolver_ignores_bad_candidates(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar que candidatos abaixo do limiar são descartados com segurança.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante regra de nunca aceitar resultado sem validação forte.
    """

    html_mismatch = """
    <html><head>
      <title>Produto Antigo Fora de Linha</title>
      <meta property="product:brand" content="Marca X" />
      <meta property="og:title" content="Produto X" />
    </head><body><div data-sku="OLD-001"></div></body></html>
    """

    html_score_05 = """
    <html><head>
      <title>One Million</title>
      <meta property="og:title" content="One Million" />
    </head><body><div data-sku="SKU-500"></div></body></html>
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)

    fetcher = FakeFetcherMap(
        {
            "https://loja.exemplo/produto-antigo": html_mismatch,
            "https://lojasrenner.com.br/p/candidato-ruim": html_score_05,
        }
    )
    provider = FakeSearchProvider(
        [
            SearchResult(
                url="https://lojasrenner.com.br/p/candidato-ruim",
                title="One Million genérico",
                source="fake",
            )
        ]
    )

    resolver = ProductResolver(store, fetcher, search_provider=provider, search_match_threshold=0.75)
    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is False
    assert result.error_code == "NO_VALID_SEARCH_CANDIDATE"

    unchanged = store.get_by_alias("one_million_200ml")
    assert unchanged is not None
    assert unchanged.last_known_url == "https://loja.exemplo/produto-antigo"
    assert unchanged.last_known_sku == "old-000"


def test_resolver_returns_fetch_failure_without_provider(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Confirmar compatibilidade quando não há provider de busca configurado.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado por teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Mantém comportamento legado para quem ainda não injeta provider.
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)
    resolver = ProductResolver(store, FakeFetcherFailure())

    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is False
    assert result.error_code == "FETCH_FAILED"


def test_resolver_returns_timeout_failure_without_provider(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Confirmar que timeout do fetch vira erro controlado no resolver.

    Parâmetros:
        tmp_path: Diretório temporário para store isolado do teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Evita regressão em cenários de páginas lentas ou indisponíveis.
    """

    store = ProductStoreService(tmp_path / "products.json")
    _seed_product(store)
    resolver = ProductResolver(store, FakeFetcherTimeout())

    result = resolver.resolve_sku_for_alias("one_million_200ml")

    assert result.success is False
    assert result.error_code == "FETCH_FAILED"
    assert "Timeout" in result.message
