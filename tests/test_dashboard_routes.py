"""
Testes básicos das rotas web do dashboard sem depender de cliente HTTP externo.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import RedirectResponse
from starlette.templating import _TemplateResponse

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ResolveResult
from backend.utils.fetcher import FetchResult
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

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": headers,
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "scheme": "http",
        "app": app,
    }
    return Request(scope=scope, receive=receive)


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
            brand="Marca X",
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
    assert "produto_teste" in content
    assert "data:image/svg+xml" in content


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
    assert "sku-inicial" in content
    assert "data:image/svg+xml" in content
    assert "imagem do produto" in content
    assert "summary-box--barcode" in content


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
    assert response.headers["location"] == "/dashboard"
    assert stored_product is not None
    assert stored_product.last_known_sku == "unknown"


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
