"""
Ponto de entrada unificado da API REST com dashboard web.

Este módulo concentra o bootstrap da aplicação FastAPI para manter compatível
o comando `uvicorn api.main:app --reload` sem perder integração com as rotas
REST novas e com o dashboard já existente no projeto.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from api.routes_products import router as products_router
from backend.services.datetime_service import ensure_process_timezone_environment
from backend.services.runtime_context import RuntimeServices, build_runtime_services
from backend.web.routes_dashboard import router as dashboard_router
from backend.web.static_files import DashboardStaticFiles


def create_app(services: RuntimeServices | None = None) -> FastAPI:
    """
    Responsabilidade:
        Inicializar a aplicação FastAPI com serviços compartilhados e rotas.

    Parâmetros:
        services: Container opcional de dependências para testes e injeção.

    Retorno:
        Instância de FastAPI pronta para execução via servidor ASGI.

    Contexto de uso:
        Função factory usada pelo Uvicorn e por testes que precisam subir a
        aplicação com dependências controladas.
    """

    # Decisão técnica:
    # O logging é configurado no bootstrap para padronizar observabilidade do
    # ambiente de desenvolvimento sem espalhar configuração por vários módulos.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    )

    ensure_process_timezone_environment()

    runtime_services = services or build_runtime_services()

    app = FastAPI(title="Product SKU Resolver", version="1.0.0")

    # Decisão técnica:
    # Mantemos tanto o container agregado quanto os atributos legados no
    # `app.state` para compatibilizar a API REST nova com o dashboard antigo.
    app.state.services = runtime_services
    app.state.product_store_service = runtime_services.product_store
    app.state.product_resolver = runtime_services.resolver

    app.include_router(products_router)
    app.include_router(dashboard_router)
    app.mount("/dashboard/static", DashboardStaticFiles(directory="backend/web/static"), name="static")

    @app.get("/", include_in_schema=False)
    def redirect_root_to_dashboard() -> RedirectResponse:
        """
        Responsabilidade:
            Redirecionar a rota raiz da aplicação para o dashboard web.

        Parâmetros:
            Nenhum.

        Retorno:
            RedirectResponse apontando para `/dashboard`.

        Contexto de uso:
            Melhora a experiência local de desenvolvimento ao abrir a aplicação
            diretamente na interface principal em vez de retornar 404.
        """

        # Decisão técnica:
        # Usamos redirecionamento explícito para preservar as rotas existentes
        # da API REST e oferecer um ponto de entrada mais amigável no navegador.
        return RedirectResponse(url="/dashboard", status_code=307)

    return app


app = create_app()
