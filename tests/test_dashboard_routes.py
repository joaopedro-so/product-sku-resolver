"""
Testes básicos das rotas web do dashboard sem depender de cliente HTTP externo.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.templating import _TemplateResponse

from backend.models.product import ProductRecord
from backend.services.manual_product_group_service import ManualProductGroupService
from backend.services.product_group_service import ProductGroupService
from backend.services.saved_product_service import SavedProductService
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ResolveResult
from backend.utils.fetcher import FetchResult
from history.history_store import HistoryStore
import pytest

try:
    from backend.web import routes_dashboard
except AssertionError as error:
    pytest.skip(f"Dependência opcional ausente para dashboard web: {error}", allow_module_level=True)
from main import create_app


class FakeResolver:
    """
    Responsabilidade:
        Simular o serviço de resolução para isolar testes da camada web.

    Parâmetros:
        Nenhum.

    Retorno:
        Instância com método `resolve_sku_for_alias` compatível com o contrato.

    Contexto de uso:
        Utilizada para validar rotas POST de update sem chamadas de rede.
    """

    def __init__(self, fetcher: object | None = None) -> None:
        """
        Responsabilidade:
            Permitir injecao opcional de fetcher para fluxos de auto-preenchimento.

        Parametros:
            fetcher: Objeto compativel com `fetch_page` usado pelo dashboard.

        Retorno:
            Nenhum.

        Contexto de uso:
            Mantem a fixture simples enquanto cobre rotas GET/POST do dashboard.
        """

        self.fetcher = fetcher

    def resolve_sku_for_alias(self, product_alias: str) -> ResolveResult:
        """
        Responsabilidade:
            Retornar um resultado de sucesso determinístico para o alias.

        Parâmetros:
            product_alias: Alias recebido pela rota de atualização.

        Retorno:
            ResolveResult com mensagem previsível para assertions.

        Contexto de uso:
            Permite testar o fluxo de redirecionamento e feedback operacional.
        """

        return ResolveResult(
            success=True,
            message=f"Atualização simulada para {product_alias}",
            product=None,
            page_data=None,
            match_result=None,
            error_code=None,
        )


class FakePageFetcher:
    """
    Responsabilidade:
        Simular download de pagina para testes do auto-preenchimento.

    Parametros:
        html_content: HTML retornado para qualquer URL enviada no teste.
        final_url: URL final devolvida apos a leitura simulada.

    Retorno:
        Instancia com metodo `fetch_page` compativel com o contrato real.

    Contexto de uso:
        Evita chamadas de rede e torna deterministica a inferencia por URL.
    """

    def __init__(self, html_content: str, final_url: str = "https://example.com/produto-final") -> None:
        """
        Responsabilidade:
            Armazenar os dados que serao devolvidos pelo fetch fake.

        Parametros:
            html_content: Documento HTML simulado.
            final_url: URL final reportada ao parser.

        Retorno:
            Nenhum.

        Contexto de uso:
            Setup de testes que precisam reproduzir parsing de pagina remota.
        """

        self.html_content = html_content
        self.final_url = final_url

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Devolver resposta fake com o HTML previamente configurado.

        Parametros:
            target_url: URL recebida pela rota sob teste.

        Retorno:
            FetchResult com HTML e URL final controlados.

        Contexto de uso:
            Substitui o fetcher real durante testes das rotas do dashboard.
        """

        return FetchResult(
            final_url=self.final_url or target_url,
            status_code=200,
            html_content=self.html_content,
        )


class FakeMappedPageFetcher:
    """
    Responsabilidade:
        Simular multiplas paginas remotas para testes de importacao interna.

    Parametros:
        responses_by_url: Mapa entre cada URL consultada e o HTML correspondente.

    Retorno:
        Instancia fake compativel com o contrato esperado pelo dashboard.

    Contexto de uso:
        Utilizada quando a rota sob teste precisa validar mais de uma pagina
        remota, como acontece na importacao curada de seed interno.
    """

    def __init__(self, responses_by_url: dict[str, FetchResult]) -> None:
        """
        Responsabilidade:
            Guardar o conjunto de respostas fake que serao usadas no teste.

        Parametros:
            responses_by_url: Dicionario indexado pela URL esperada.

        Retorno:
            Nenhum.

        Contexto de uso:
            Mantem o fake pequeno e explicito, sem depender de rede.
        """

        self.responses_by_url = responses_by_url

    def fetch_page(self, target_url: str) -> FetchResult:
        """
        Responsabilidade:
            Retornar a resposta fake correspondente a URL solicitada.

        Parametros:
            target_url: URL consultada pelo fluxo sob teste.

        Retorno:
            FetchResult configurado previamente pelo teste.

        Contexto de uso:
            Permite simular varias paginas da Renner em um unico cenario.
        """

        if target_url not in self.responses_by_url:
            raise AssertionError(f"URL nao prevista no teste: {target_url}")
        return self.responses_by_url[target_url]


class FailingPersistProductStore(ProductStoreService):
    """
    Responsabilidade:
        Simular falha de persistencia no cadastro para testar feedback de erro.

    Parametros:
        storage_file_path: Caminho do arquivo, mantido por compatibilidade.

    Retorno:
        Instancia de store que sempre falha ao tentar salvar um produto.

    Contexto de uso:
        Permite validar que o dashboard nao retorna sucesso falso quando o
        storage real nao consegue confirmar a gravacao.
    """

    def upsert_product(self, product_to_save: ProductRecord) -> ProductRecord:
        """
        Responsabilidade:
            Forcar uma falha de escrita previsivel durante o cadastro.

        Parametros:
            product_to_save: Produto que seria persistido pelo fluxo real.

        Retorno:
            Nunca retorna; sempre levanta RuntimeError controlado.

        Contexto de uso:
            Isola o teste de UX de erro sem depender de falhas de IO reais.
        """

        raise RuntimeError("falha simulada de persistencia")


def _build_app_with_temp_storage(tmp_path: Path) -> FastAPI:
    """
    Responsabilidade:
        Criar app de teste com storage temporário e resolver fake.

    Parâmetros:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Retorno:
        Instância de FastAPI pronta para uso pelas funções de rota.

    Contexto de uso:
        Evita escrita em `data/products.json` e mantém testes isolados.
    """

    app = create_app()
    app.state.product_store_service = ProductStoreService(tmp_path / "products.json")
    app.state.product_resolver = FakeResolver()
    app.state.history_store_service = HistoryStore(tmp_path / "history.json")
    app.state.saved_product_service = SavedProductService(tmp_path / "saved_products.json")
    return app


def _build_request(app: FastAPI, method: str, path: str, body: bytes = b"", content_type: str = "") -> Request:
    """
    Responsabilidade:
        Construir objeto Request mínimo para invocar rota diretamente.

    Parâmetros:
        app: Aplicação FastAPI que contém serviços no app state.
        method: Método HTTP simulado (GET/POST).
        path: Caminho da rota simulada.
        body: Corpo bruto da requisição para cenários de formulário.
        content_type: Content-Type necessário para parsing de formulário.

    Retorno:
        Request configurada com scope ASGI e receiver assíncrono.

    Contexto de uso:
        Estratégia para testar handlers sem `TestClient` (dependência httpx).
    """

    has_consumed = False

    async def receive() -> dict:
        """Retornar payload único no formato ASGI para leitura do corpo."""

        nonlocal has_consumed
        if has_consumed:
            return {"type": "http.request", "body": b"", "more_body": False}
        has_consumed = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = []
    if content_type:
        headers.append((b"content-type", content_type.encode("utf-8")))

    parsed_path = urlsplit(path)
    normalized_path = parsed_path.path or path
    query_string = parsed_path.query.encode("utf-8")

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": normalized_path,
        "raw_path": path.encode("utf-8"),
        "query_string": query_string,
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": app,
    }
    return Request(scope=scope, receive=receive)


def _configure_manual_product_groups(app: FastAPI, tmp_path: Path, payload: dict) -> None:
    """
    Responsabilidade:
        Injetar um arquivo temporario de grupos manuais no app de teste.

    Parametros:
        app: Instancia FastAPI usada no teste atual.
        tmp_path: Diretorio temporario do pytest para gravar o arquivo.
        payload: Conteudo JSON do override manual desejado no teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Permite validar o comportamento das rotas com curadoria manual sem
        depender do arquivo real versionado no repositorio.
    """

    manual_group_file = tmp_path / "manual_product_groups.json"
    manual_group_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    app.state.product_group_service = ProductGroupService(
        manual_group_service=ManualProductGroupService(storage_file_path=manual_group_file)
    )


def _seed_product(app: FastAPI) -> None:
    """
    Responsabilidade:
        Inserir produto base no storage para cenários de listagem/detalhe/update.

    Parâmetros:
        app: Aplicação contendo `product_store_service` no app state.

    Retorno:
        Nenhum.

    Contexto de uso:
        Reaproveitado entre testes para reduzir duplicação de setup.
    """

    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="produto_teste",
            brand="Paco Rabanne",
            name="Produto X",
            variant="100ml",
            last_known_url="https://example.com/produto",
            last_known_sku="sku-inicial",
        )
    )


def test_dashboard_home_carrega_lista_de_produtos(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Verificar renderização da listagem principal do dashboard.

    Parâmetros:
        tmp_path: Diretório temporário para isolamento do arquivo de produtos.

    Retorno:
        Nenhum; valida conteúdo HTML de saída.

    Contexto de uso:
        Cobertura da rota GET `/dashboard`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard")

    response = routes_dashboard.dashboard_home(request)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Perfumaria Prestígio" in content
    assert "Prateleira 01 — Perfumes Árabes" in content
    assert "Prateleira 02 — Azzaro" in content
    assert "Prateleira 03 — Calvin Klein" in content
    assert "Prateleira 04 — Paco Rabanne" in content
    assert "Prateleira 05 — Carolina Herrera A" in content
    assert "Prateleira 06 — Carolina Herrera B" in content
    assert "Prateleira 07 — Lancôme" in content
    assert "Prateleira 08 — Giorgio Armani" in content
    assert "Prateleira 09 — Ralph Lauren" in content
    assert "Buscar produto, marca ou SKU" in content
    assert "Importar do site" in content
    assert "Cadastrar manualmente" in content
    assert "/dashboard/static/shelf-banners/shelf-04-paco-rabanne.png" in content


def test_dashboard_importa_seed_interno_pela_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Responsabilidade:
        Garantir que a acao web importe o seed interno no storage atual.

    Parametros:
        tmp_path: Diretorio temporario para isolar o arquivo de produtos.
        monkeypatch: Fixture do pytest para redirecionar o seed interno.

    Retorno:
        Nenhum; valida redirecionamento e persistencia dos itens importados.

    Contexto de uso:
        Protege o fluxo pensado para a Railway, onde a importacao precisa
        acontecer pelo proprio painel web sem shell manual.
    """

    seed_file_path = tmp_path / "seed_import.json"
    seed_file_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "alias": "produto_importado_50ml",
                        "brand": "Marca Importada",
                        "name": "Produto Importado",
                        "variant": "50ml",
                        "sku": "123456",
                        "page_url": "https://www.lojasrenner.com.br/p/produto-importado/-/A-123-br.lr",
                        "shelf_number": 3,
                        "display_order": 1,
                        "expected_title_fragment": "produto importado",
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        routes_dashboard,
        "resolve_builtin_curated_seed_file",
        lambda seed_name: seed_file_path,
    )

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_resolver = FakeResolver(
        fetcher=FakeMappedPageFetcher(
            {
                "https://www.lojasrenner.com.br/p/produto-importado/-/A-123-br.lr": FetchResult(
                    final_url="https://www.lojasrenner.com.br/p/produto-importado/-/A-123-br.lr",
                    status_code=200,
                    html_content=(
                        "<html><head>"
                        "<title>Produto Importado 50ml - Lojas Renner</title>"
                        "<meta property=\"og:title\" content=\"Produto Importado 50ml - Lojas Renner\"/>"
                        "</head><body>"
                        "<input type=\"radio\" data-name=\"50ml\" data-sku=\"123456\" />"
                        "</body></html>"
                    ),
                )
            }
        )
    )
    request = _build_request(app, method="POST", path="/dashboard/imports/prestige-shelf-03")

    response = routes_dashboard.dashboard_import_prestige_shelf_03(request)

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert "import_status=success" in response.headers["location"]
    stored_product = app.state.product_store_service.get_by_alias("produto_importado_50ml")
    assert stored_product is not None
    assert stored_product.shelf_number == 3
    assert stored_product.last_known_sku == "123456"


def test_dashboard_abre_detalhe_da_prateleira_com_produtos_alocados(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a rota da prateleira mostra os produtos nela alocados.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida shelf correta e produto renderizado.

    Contexto de uso:
        Cobertura da rota GET `/dashboard/prateleiras/{numero}`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard/prateleiras/4")

    response = routes_dashboard.dashboard_shelf_detail(request, shelf_number=4)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Paco Rabanne" in content
    assert "Produto X" in content
    assert "Código" in content
    assert "Abrir" in content
    assert "/dashboard/static/shelf-banners/shelf-04-paco-rabanne.png" in content


def test_dashboard_prateleira_agrupa_variantes_em_um_unico_card(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que variantes de volume virem um unico card na prateleira.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida agrupamento visual e presenca dos chips de variante.

    Contexto de uso:
        Protege a nova IA da prateleira, que deve representar um perfume pai
        apenas uma vez, mesmo quando existirem varios volumes cadastrados.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="good_girl_30ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="30ml",
            last_known_url="https://example.com/good-girl?sku=30",
            last_known_sku="sku-30",
            shelf_number=5,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="good_girl_50ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="50ml",
            last_known_url="https://example.com/good-girl?sku=50",
            last_known_sku="sku-50",
            shelf_number=5,
        )
    )
    request = _build_request(app, method="GET", path="/dashboard/prateleiras/5")

    response = routes_dashboard.dashboard_shelf_detail(request, shelf_number=5)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert content.count('class="shelf-product-card"') == 1
    assert "Good Girl" in content
    assert "30ml" in content
    assert "50ml" in content
    assert 'data-variant-code-label' in content


def test_dashboard_detalhe_agrupa_variantes_sem_trocar_de_produto(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o detalhe exponha seletor de variantes do mesmo perfume pai.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida chips, acoes por variante e SKU inicial selecionado.

    Contexto de uso:
        Protege a tela operacional em que o operador precisa trocar volume sem
        sair do mesmo produto pai para acessar outro barcode.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="good_girl_30ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="30ml",
            last_known_url="https://example.com/good-girl?sku=30",
            last_known_sku="sku-30",
            shelf_number=5,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="good_girl_50ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="50ml",
            last_known_url="https://example.com/good-girl?sku=50",
            last_known_sku="sku-50",
            shelf_number=5,
        )
    )
    request = _build_request(app, method="GET", path="/dashboard/products/good_girl_50ml")

    response = routes_dashboard.dashboard_product_detail(request, alias="good_girl_50ml")

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Good Girl" in content
    assert "30ml" in content
    assert "50ml" in content
    assert "sku-50" in content
    assert "/dashboard/products/good_girl_30ml/barcode" in content
    assert "/dashboard/products/good_girl_50ml/barcode" in content


def test_dashboard_prateleira_exibe_filtros_dinamicos_de_marca_e_combina_com_busca(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a prateleira trate a marca como filtro e nao como exclusividade.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida chips de marca e combinacao com busca textual.

    Contexto de uso:
        Protege a leitura correta da prateleira como localizacao fisica, onde
        podem coexistir itens de marcas diferentes no mesmo expositor.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="good_girl_50ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="50ml",
            last_known_url="https://example.com/good-girl?sku=50",
            last_known_sku="sku-50",
            shelf_number=5,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="idole_50ml",
            brand="Lancôme",
            name="Idôle",
            variant="50ml",
            last_known_url="https://example.com/idole?sku=50",
            last_known_sku="sku-idole",
            shelf_number=5,
        )
    )
    request = _build_request(
        app,
        method="GET",
        path=f"/dashboard/prateleiras/5?{urlencode({'brand': 'Lancôme', 'q': 'Idôle'})}",
    )

    response = routes_dashboard.dashboard_shelf_detail(request, shelf_number=5)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Referência:" in content
    assert "Todas" in content
    assert "Carolina Herrera" in content
    assert "Lancôme" in content
    assert "sku-idole" in content
    assert "sku-50" not in content


def test_dashboard_respeita_prateleira_manual_no_cadastro(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o produto use a prateleira escolhida manualmente.

    Parametros:
        tmp_path: Diretorio temporario para isolamento da base.

    Retorno:
        Nenhum; valida persistencia e exibicao da localizacao manual.

    Contexto de uso:
        Cobertura do novo fluxo de atribuicao de prateleira no formulario.
    """

    app = _build_app_with_temp_storage(tmp_path)
    payload = urlencode(
        {
            "alias": "produto_manual",
            "brand": "Marca Y",
            "name": "Produto Manual",
            "variant": "50ml",
            "last_known_url": "https://example.com/manual",
            "last_known_sku": "sku-manual",
            "shelf_number": "8",
            "display_order": "2",
        }
    ).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_create_product(request))
    stored_product = app.state.product_store_service.get_by_alias("produto_manual")

    assert isinstance(response, RedirectResponse)
    assert stored_product is not None
    assert stored_product.shelf_number == 8
    assert stored_product.display_order == 2

    shelf_request = _build_request(app, method="GET", path="/dashboard/prateleiras/8")
    shelf_response = routes_dashboard.dashboard_shelf_detail(shelf_request, shelf_number=8)
    shelf_content = shelf_response.body.decode("utf-8")
    assert "Produto Manual" in shelf_content


def test_dashboard_search_renderiza_lista_operacional(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a tela Search exibe lista mobile-first com filtros.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida campos essenciais da busca.

    Contexto de uso:
        Cobertura da rota GET `/dashboard/search`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard/search")

    response = routes_dashboard.dashboard_search(request)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Resultados" in content
    assert "Produto X" in content
    assert "SKU" in content


def test_dashboard_detalhe_abre_produto_existente(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a rota de detalhe retorna produto cadastrado.

    Parâmetros:
        tmp_path: Diretório temporário para storage do teste.

    Retorno:
        Nenhum; valida status e campos essenciais da página.

    Contexto de uso:
        Cobertura da rota GET `/dashboard/products/{alias}`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard/products/produto_teste")

    response = routes_dashboard.dashboard_product_detail(request, alias="produto_teste")

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Produto X" in content
    assert "Prateleira 04 — Paco Rabanne" in content
    assert "sku-inicial" in content
    assert "Imagem do produto" in content
    assert "Código de barras" in content
    assert "Código em tela cheia" in content


def test_dashboard_barcode_fullscreen_exibe_modo_operacional(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar a tela dedicada de barcode fullscreen para uso operacional.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida a presenca do SKU e acoes principais.

    Contexto de uso:
        Cobertura da rota GET `/dashboard/products/{alias}/barcode`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard/products/produto_teste/barcode")

    response = routes_dashboard.dashboard_product_barcode_fullscreen(request, alias="produto_teste")

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Fechar" in content
    assert "sku-inicial" in content
    assert "Atualizar" in content


def test_dashboard_cria_produto_via_formulario(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar persistência de produto quando formulário é submetido.

    Parâmetros:
        tmp_path: Diretório temporário para isolamento da base de produtos.

    Retorno:
        Nenhum; valida redirecionamento e objeto persistido.

    Contexto de uso:
        Cobertura da rota POST `/dashboard/products`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    payload = urlencode(
        {
            "alias": "novo_produto",
            "brand": "Marca Y",
            "name": "Produto Y",
            "variant": "50ml",
            "last_known_url": "https://example.com/novo-produto",
        }
    ).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_create_product(request))
    stored_product = app.state.product_store_service.get_by_alias("novo_produto")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/products/novo_produto?created=1"
    assert stored_product is not None
    assert stored_product.last_known_sku == "unknown"


def test_dashboard_create_product_sobrevive_a_nova_sessao_e_aparece_na_busca(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o cadastro persista apos reabrir o app e reler a lista.

    Parametros:
        tmp_path: Diretorio temporario usado como storage persistente do teste.

    Retorno:
        Nenhum; valida persistencia, refresh e nova sessao.

    Contexto de uso:
        Cobre o bug principal reportado pelo operador, em que o produto parecia
        ter sido salvo mas nao reaparecia de forma confiavel depois.
    """

    first_app = _build_app_with_temp_storage(tmp_path)
    payload = urlencode(
        {
            "alias": "perfume_persistente",
            "brand": "Marca Z",
            "name": "Perfume Persistente",
            "variant": "100ml",
            "last_known_url": "https://example.com/perfume-persistente",
            "last_known_sku": "sku-persistente",
            "shelf_number": "8",
        }
    ).encode("utf-8")
    create_request = _build_request(
        first_app,
        method="POST",
        path="/dashboard/products",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    create_response = asyncio.run(routes_dashboard.dashboard_create_product(create_request))

    second_app = _build_app_with_temp_storage(tmp_path)
    detail_request = _build_request(
        second_app,
        method="GET",
        path="/dashboard/products/perfume_persistente?created=1",
    )
    search_request = _build_request(
        second_app,
        method="GET",
        path="/dashboard/search?q=perfume_persistente",
    )

    detail_response = routes_dashboard.dashboard_product_detail(detail_request, alias="perfume_persistente")
    search_response = routes_dashboard.dashboard_search(search_request)

    assert isinstance(create_response, RedirectResponse)
    assert create_response.status_code == 303
    assert isinstance(detail_response, _TemplateResponse)
    assert detail_response.status_code == 200
    assert isinstance(search_response, _TemplateResponse)
    assert search_response.status_code == 200
    assert second_app.state.product_store_service.get_by_alias("perfume_persistente") is not None
    assert "Produto salvo com sucesso" in detail_response.body.decode("utf-8")
    assert "Perfume Persistente" in search_response.body.decode("utf-8")


def test_dashboard_create_product_exibe_erro_real_quando_persistencia_falha(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a UI nao mostre sucesso falso quando salvar falha.

    Parametros:
        tmp_path: Diretorio temporario para manter a fixture do app isolada.

    Retorno:
        Nenhum; valida erro visivel e ausencia de redirect de sucesso.

    Contexto de uso:
        Protege o fluxo de cadastro contra falhas silenciosas do storage.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service = FailingPersistProductStore(tmp_path / "products.json")
    payload = urlencode(
        {
            "alias": "produto_falha",
            "brand": "Marca",
            "name": "Produto com Falha",
            "variant": "100ml",
            "last_known_url": "https://example.com/falha",
            "last_known_sku": "sku-falha",
        }
    ).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_create_product(request))

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 500
    content = response.body.decode("utf-8")
    assert "Nao foi possivel salvar o produto" in content
    assert "falha simulada de persistencia" in content
    assert app.state.product_store_service.get_by_alias("produto_falha") is None


def test_dashboard_cria_produto_manual_com_variantes_e_persistencia_real(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o cadastro manual persista variantes com estoque e origem.

    Parametros:
        tmp_path: Diretorio temporario para isolar os arquivos do app.

    Retorno:
        Nenhum; valida redirect, storage, detalhe e sobrevivencia ao reload.

    Contexto de uso:
        Protege o novo fluxo de perfumes internos que nao existem mais no site,
        mas ainda precisam de barcode e localizacao na perfumaria.
    """

    first_app = _build_app_with_temp_storage(tmp_path)
    payload = urlencode(
        [
            ("source_type", "manual"),
            ("alias", "good_girl_interno"),
            ("brand", "Carolina Herrera"),
            ("name", "Good Girl"),
            ("concentration", "EDP"),
            ("shelf_number", "5"),
            ("display_order", "2"),
            ("notes", "Cadastro interno da perfumaria."),
            ("manual_variant_label", "50ml"),
            ("manual_variant_code", "111222333"),
            ("manual_variant_stock_qty", "2"),
            ("manual_variant_notes", "Frasco principal."),
            ("manual_variant_alias", "good_girl_interno_50ml"),
            ("manual_variant_label", "80ml"),
            ("manual_variant_code", "444555666"),
            ("manual_variant_stock_qty", "1"),
            ("manual_variant_notes", "Ultima unidade."),
            ("manual_variant_alias", "good_girl_interno_80ml"),
        ],
        doseq=True,
    ).encode("utf-8")
    create_request = _build_request(
        first_app,
        method="POST",
        path="/dashboard/products",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    create_response = asyncio.run(routes_dashboard.dashboard_create_product(create_request))

    assert isinstance(create_response, RedirectResponse)
    assert create_response.status_code == 303
    assert create_response.headers["location"] == "/dashboard/products/good_girl_interno_50ml?created=1"

    stored_variant_50ml = first_app.state.product_store_service.get_by_alias("good_girl_interno_50ml")
    stored_variant_80ml = first_app.state.product_store_service.get_by_alias("good_girl_interno_80ml")
    assert stored_variant_50ml is not None
    assert stored_variant_80ml is not None
    assert stored_variant_50ml.source_type == "manual"
    assert stored_variant_80ml.source_type == "manual"
    assert stored_variant_50ml.stock_qty == 2
    assert stored_variant_80ml.stock_qty == 1
    assert stored_variant_50ml.parent_reference == stored_variant_80ml.parent_reference
    assert stored_variant_50ml.shelf_number == 5

    second_app = _build_app_with_temp_storage(tmp_path)
    reloaded_variant_50ml = second_app.state.product_store_service.get_by_alias("good_girl_interno_50ml")
    assert reloaded_variant_50ml is not None
    assert reloaded_variant_50ml.source_type == "manual"
    assert reloaded_variant_50ml.stock_qty == 2

    detail_request = _build_request(second_app, method="GET", path="/dashboard/products/good_girl_interno_50ml?created=1")
    detail_response = routes_dashboard.dashboard_product_detail(detail_request, alias="good_girl_interno_50ml")
    detail_content = detail_response.body.decode("utf-8")

    assert isinstance(detail_response, _TemplateResponse)
    assert detail_response.status_code == 200
    assert "Good Girl" in detail_content
    assert "Cadastro interno" in detail_content
    assert "Código em tela cheia" in detail_content
    assert "Estoque" in detail_content
    assert "111222333" in detail_content
    assert "444555666" in detail_content

    shelf_request = _build_request(second_app, method="GET", path="/dashboard/prateleiras/5")
    shelf_response = routes_dashboard.dashboard_shelf_detail(shelf_request, shelf_number=5)
    shelf_content = shelf_response.body.decode("utf-8")

    assert "Good Girl" in shelf_content
    assert "50ml" in shelf_content
    assert "80ml" in shelf_content
    assert "Cadastro interno" in shelf_content


def test_dashboard_bloqueia_update_para_produto_manual(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que itens manuais nao sejam tratados como erro de sync.

    Parametros:
        tmp_path: Diretorio temporario para isolar os arquivos do app.

    Retorno:
        Nenhum; valida redirect explicativo ao tentar atualizar manualmente.

    Contexto de uso:
        Protege a UX para perfumes internos e legados, que precisam aparecer
        no catalogo sem disparar um pipeline que depende do site.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="manual_barcode",
            brand="Marca Interna",
            name="Perfume Interno",
            variant="100ml",
            last_known_url="",
            last_known_sku="998877665",
            source_type="manual",
            shelf_number=1,
            stock_qty=3,
        )
    )
    update_request = _build_request(app, method="POST", path="/dashboard/products/manual_barcode/update")
    update_response = routes_dashboard.dashboard_update_product(update_request, alias="manual_barcode")

    assert isinstance(update_response, RedirectResponse)
    assert update_response.status_code == 303
    assert update_response.headers["location"] == "/dashboard/products/manual_barcode?sync_blocked=1"

    detail_request = _build_request(app, method="GET", path="/dashboard/products/manual_barcode?sync_blocked=1")
    detail_response = routes_dashboard.dashboard_product_detail(detail_request, alias="manual_barcode")
    detail_content = detail_response.body.decode("utf-8")

    assert "nao depende mais da sincronizacao do site" in detail_content.lower()


def test_dashboard_aciona_update_de_produto(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Confirmar redirecionamento da ação de update individual.

    Parâmetros:
        tmp_path: Diretório temporário para isolamento dos dados.

    Retorno:
        Nenhum; valida status HTTP e URL de destino.

    Contexto de uso:
        Cobertura da rota POST `/dashboard/products/{alias}/update`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="POST", path="/dashboard/products/produto_teste/update")

    response = routes_dashboard.dashboard_update_product(request, alias="produto_teste")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/products/produto_teste"


def test_dashboard_abre_formulario_de_edicao(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a tela de edicao carrega os dados atuais do produto.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida o HTML preenchido devolvido pela rota.

    Contexto de uso:
        Cobertura da rota GET `/dashboard/products/{alias}/edit`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard/products/produto_teste/edit")

    response = routes_dashboard.dashboard_edit_product_form(request, alias="produto_teste")

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Editar produto" in content
    assert "produto_teste" in content
    assert "sku-inicial" in content
    assert "Salvar alteracoes" in content


def test_dashboard_salva_produto_em_saved(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a acao de salvar adiciona o produto na aba Saved.

    Parametros:
        tmp_path: Diretorio temporario para isolamento da base.

    Retorno:
        Nenhum; valida redirect e persistencia do alias salvo.

    Contexto de uso:
        Cobertura da rota POST `/dashboard/products/{alias}/toggle-saved`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    payload = urlencode({"next": "/dashboard/saved"}).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products/produto_teste/toggle-saved",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_toggle_saved_product(request, alias="produto_teste"))

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/saved"
    assert app.state.saved_product_service.is_saved("produto_teste") is True


def test_dashboard_exclui_produto_e_limpa_salvo(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a exclusao remova o produto do catalogo e da lista de salvos.

    Parametros:
        tmp_path: Diretorio temporario para isolamento da base.

    Retorno:
        Nenhum; valida redirect, remocao do storage e limpeza de atalhos.

    Contexto de uso:
        Cobre a nova acao administrativa de exclusao na interface web.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    app.state.saved_product_service.save_alias("produto_teste")
    request = _build_request(app, method="POST", path="/dashboard/products/produto_teste/delete")

    response = routes_dashboard.dashboard_delete_product(request, alias="produto_teste")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard"
    assert app.state.product_store_service.get_by_alias("produto_teste") is None
    assert app.state.saved_product_service.is_saved("produto_teste") is False


def test_dashboard_updates_renderiza_resumo_operacional(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a tela Updates carrega com resumo operacional compreensivel.

    Parametros:
        tmp_path: Diretorio temporario para isolamento da base.

    Retorno:
        Nenhum; valida se a interface principal de updates renderiza.

    Contexto de uso:
        Cobertura da rota GET `/dashboard/updates`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    request = _build_request(app, method="GET", path="/dashboard/updates")

    response = routes_dashboard.dashboard_updates(request)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Resumo da sincronização" in content
    assert "Atualizar todos" in content


def test_dashboard_salva_edicao_de_produto_com_novo_alias(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar persistencia da edicao quando o operador altera alias e campos.

    Parametros:
        tmp_path: Diretorio temporario para isolamento da base de produtos.

    Retorno:
        Nenhum; valida redirecionamento e estado final persistido.

    Contexto de uso:
        Cobertura da rota POST `/dashboard/products/{alias}/edit`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    payload = urlencode(
        {
            "alias": "produto_editado",
            "brand": "Marca Z",
            "name": "Produto Z",
            "variant": "150ml",
            "last_known_url": "https://example.com/produto-editado",
            "last_known_sku": "sku-editado",
        }
    ).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products/produto_teste/edit",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_edit_product(request, alias="produto_teste"))

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/products/produto_editado"
    assert app.state.product_store_service.get_by_alias("produto_teste") is None
    updated_product = app.state.product_store_service.get_by_alias("produto_editado")
    assert updated_product is not None
    assert updated_product.brand == "Marca Z"
    assert updated_product.last_known_sku == "sku-editado"


def test_dashboard_salva_edicao_de_produto_com_prateleira_manual(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a edicao permita redefinir a prateleira manual do produto.

    Parametros:
        tmp_path: Diretorio temporario para isolamento da base de produtos.

    Retorno:
        Nenhum; valida persistencia e reflexo da nova localizacao na interface.

    Contexto de uso:
        Protege o fluxo operacional em que o time reorganiza produtos fisicamente
        e precisa ajustar a prateleira sem depender da inferencia automatica.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _seed_product(app)
    payload = urlencode(
        {
            "alias": "produto_teste",
            "brand": "Paco Rabanne",
            "name": "Produto X",
            "variant": "100ml",
            "last_known_url": "https://example.com/produto",
            "last_known_sku": "sku-inicial",
            "shelf_number": "9",
            "display_order": "1",
        }
    ).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products/produto_teste/edit",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_edit_product(request, alias="produto_teste"))
    updated_product = app.state.product_store_service.get_by_alias("produto_teste")

    assert isinstance(response, RedirectResponse)
    assert updated_product is not None
    assert updated_product.shelf_number == 9
    assert updated_product.display_order == 1

    shelf_request = _build_request(app, method="GET", path="/dashboard/prateleiras/9")
    shelf_response = routes_dashboard.dashboard_shelf_detail(shelf_request, shelf_number=9)
    shelf_content = shelf_response.body.decode("utf-8")
    assert "Produto X" in shelf_content


def test_dashboard_preenche_produto_automaticamente_por_url(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a rota de auto-preenchimento sugere os campos do cadastro.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida o HTML preenchido devolvido ao formulario.

    Contexto de uso:
        Cobertura da rota POST `/dashboard/products/auto-fill`.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_resolver = FakeResolver(
        fetcher=FakePageFetcher(
            html_content="""
            <html>
              <head>
                <title>Paco Rabanne One Million 200ml - Renner</title>
                <meta property="product:brand" content="Paco Rabanne" />
                <meta property="og:title" content="Paco Rabanne One Million 200ml - Renner" />
                <meta property="og:image" content="/images/one-million.png" />
              </head>
              <body>
                <script type="application/ld+json">
                  {"sku": "546594103"}
                </script>
              </body>
            </html>
            """,
        )
    )
    payload = urlencode({"last_known_url": "https://example.com/produto"}).encode("utf-8")
    request = _build_request(
        app,
        method="POST",
        path="/dashboard/products/auto-fill",
        body=payload,
        content_type="application/x-www-form-urlencoded",
    )

    response = asyncio.run(routes_dashboard.dashboard_autofill_product_form(request))

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Paco Rabanne" in content
    assert "One Million" in content
    assert "200ml" in content
    assert "546594103" in content
    assert "paco_rabanne_one_million_200ml" in content


def test_dashboard_prateleira_respeita_agrupamento_manual_de_variantes(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a prateleira use grupos manuais antes do fallback automatico.

    Parametros:
        tmp_path: Diretorio temporario para storage e arquivo de override.

    Retorno:
        Nenhum; valida card unico para variantes curadas manualmente.

    Contexto de uso:
        Protege a tela principal do operador quando o site separa volumes do
        mesmo perfume em paginas distintas e a curadoria precisa uni-los.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _configure_manual_product_groups(
        app=app,
        tmp_path=tmp_path,
        payload={
            "groups": [
                {
                    "group_id": "the_icon_edt",
                    "family_name": "The Icon",
                    "display_name": "The Icon Eau de Toilette",
                    "brand": "Antonio Banderas",
                    "variant_members": [
                        {"alias": "the_icon_edt_50ml", "label": "50ml"},
                        {"alias": "the_icon_edt_100ml", "label": "100ml"},
                    ],
                }
            ]
        },
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_edt_50ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Toilette",
            variant="50ml",
            last_known_url="https://example.com/the-icon-edt-50",
            last_known_sku="sku-edt-50",
            shelf_number=2,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_edt_100ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Toilette",
            variant="100ml",
            last_known_url="https://example.com/the-icon-edt-100",
            last_known_sku="sku-edt-100",
            shelf_number=2,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_edp_100ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Parfum",
            variant="100ml",
            last_known_url="https://example.com/the-icon-edp-100",
            last_known_sku="sku-edp-100",
            shelf_number=2,
        )
    )
    request = _build_request(app, method="GET", path="/dashboard/prateleiras/2")

    response = routes_dashboard.dashboard_shelf_detail(request, shelf_number=2)

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert content.count('class="shelf-product-card"') == 2
    assert "The Icon Eau de Toilette" in content
    assert "The Icon Eau de Parfum" in content
    assert "50ml" in content
    assert "100ml" in content


def test_dashboard_detalhe_respeita_agrupamento_manual_sem_mesclar_produtos_distintos(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o detalhe troque apenas entre variantes do grupo manual.

    Parametros:
        tmp_path: Diretorio temporario para storage e arquivo de override.

    Retorno:
        Nenhum; valida seletor restrito ao grupo manual configurado.

    Contexto de uso:
        Evita que EDT, EDP e flankers semelhantes acabem misturados na mesma
        tela de detalhe quando a curadoria definiu grupos separados.
    """

    app = _build_app_with_temp_storage(tmp_path)
    _configure_manual_product_groups(
        app=app,
        tmp_path=tmp_path,
        payload={
            "groups": [
                {
                    "group_id": "the_icon_edt",
                    "family_name": "The Icon",
                    "display_name": "The Icon Eau de Toilette",
                    "brand": "Antonio Banderas",
                    "variant_members": [
                        {"alias": "the_icon_edt_50ml", "label": "50ml"},
                        {"alias": "the_icon_edt_100ml", "label": "100ml"},
                    ],
                }
            ]
        },
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_edt_50ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Toilette",
            variant="50ml",
            last_known_url="https://example.com/the-icon-edt-50",
            last_known_sku="sku-edt-50",
            shelf_number=2,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_edt_100ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Toilette",
            variant="100ml",
            last_known_url="https://example.com/the-icon-edt-100",
            last_known_sku="sku-edt-100",
            shelf_number=2,
        )
    )
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_edp_100ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Parfum",
            variant="100ml",
            last_known_url="https://example.com/the-icon-edp-100",
            last_known_sku="sku-edp-100",
            shelf_number=2,
        )
    )
    request = _build_request(app, method="GET", path="/dashboard/products/the_icon_edt_100ml")

    response = routes_dashboard.dashboard_product_detail(request, alias="the_icon_edt_100ml")

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "The Icon Eau de Toilette" in content
    assert "50ml" in content
    assert "100ml" in content
    assert "sku-edt-100" in content
    assert "/dashboard/products/the_icon_edt_50ml/barcode" in content
    assert "/dashboard/products/the_icon_edt_100ml/barcode" in content
    assert 'data-variant-alias="the_icon_edp_100ml"' not in content


def test_dashboard_detalhe_exibe_bloco_de_candidato_quando_o_item_pode_voltar_ao_site(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a PDP mostre a revisao manual de vinculo quando houver candidato.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida o bloco de confirmacao manual no detalhe do produto.

    Contexto de uso:
        Protege a nova UX de reconciliacao, onde o operador decide se um item
        manual realmente corresponde ao produto que voltou ao site.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="ck_one_interno_100ml",
            brand="Calvin Klein",
            name="CK One Eau de Toilette",
            variant="100ml",
            last_known_url="",
            last_known_sku="manual-100",
            source_type="manual",
            site_link_status="candidate_found",
            site_candidate_id="111",
            site_candidate_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=999",
            site_candidate_code="999",
            match_confidence=0.88,
            match_signals=["Marca compatível", "Variante compatível"],
            shelf_number=3,
        )
    )
    request = _build_request(app, method="GET", path="/dashboard/products/ck_one_interno_100ml")

    response = routes_dashboard.dashboard_product_detail(request, alias="ck_one_interno_100ml")

    assert isinstance(response, _TemplateResponse)
    assert response.status_code == 200
    content = response.body.decode("utf-8")
    assert "Possível correspondência encontrada" in content
    assert "Vincular item" in content
    assert "Ignorar" in content
    assert "999" in content
    assert "111" in content


def test_dashboard_confirma_candidato_e_retoma_sync_no_mesmo_alias(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a rota web confirme o candidato e preserve o alias interno.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida redirect e estado final persistido.

    Contexto de uso:
        Cobre a acao administrativa usada na PDP para religar um item manual ao site.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="ck_one_interno_100ml",
            brand="Calvin Klein",
            name="CK One Eau de Toilette",
            variant="100ml",
            last_known_url="",
            last_known_sku="manual-100",
            source_type="manual",
            site_link_status="candidate_found",
            site_candidate_id="111",
            site_candidate_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=999",
            site_candidate_code="999",
            shelf_number=3,
        )
    )
    request = _build_request(app, method="POST", path="/dashboard/products/ck_one_interno_100ml/confirm-site-link")

    response = routes_dashboard.dashboard_confirm_site_link(request, alias="ck_one_interno_100ml")
    updated_product = app.state.product_store_service.get_by_alias("ck_one_interno_100ml")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/products/ck_one_interno_100ml?site_linked=1"
    assert updated_product is not None
    assert updated_product.site_link_status == "linked_to_site"
    assert updated_product.last_known_sku == "999"
    assert updated_product.shelf_number == 3


def test_dashboard_permita_ignorar_candidato_sem_remover_produto_manual(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a rota web descarte o candidato e mantenha o item manual.

    Parametros:
        tmp_path: Diretorio temporario para isolamento do storage.

    Retorno:
        Nenhum; valida redirect e limpeza do estado de candidato.

    Contexto de uso:
        Cobre a acao usada quando a sugestao do site nao representa o perfume real.
    """

    app = _build_app_with_temp_storage(tmp_path)
    app.state.product_store_service.upsert_product(
        ProductRecord(
            alias="the_icon_interno_100ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Toilette",
            variant="100ml",
            last_known_url="",
            last_known_sku="manual-100",
            source_type="manual",
            site_link_status="candidate_found",
            site_candidate_id="222",
            site_candidate_url="https://www.lojasrenner.com.br/p/the-icon/-/A-222-br.lr?sku=333",
            site_candidate_code="333",
        )
    )
    request = _build_request(app, method="POST", path="/dashboard/products/the_icon_interno_100ml/ignore-site-candidate")

    response = routes_dashboard.dashboard_ignore_site_candidate(request, alias="the_icon_interno_100ml")
    updated_product = app.state.product_store_service.get_by_alias("the_icon_interno_100ml")

    assert isinstance(response, RedirectResponse)
    assert response.status_code == 303
    assert response.headers["location"] == "/dashboard/products/the_icon_interno_100ml?site_candidate_ignored=1"
    assert updated_product is not None
    assert updated_product.site_link_status == "manual_unlinked"
    assert updated_product.last_known_sku == "manual-100"
