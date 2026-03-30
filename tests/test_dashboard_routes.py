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
