"""
Ponto de entrada da aplicação FastAPI com API e dashboard web.

Este bootstrap injeta serviços compartilhados no app state para que as rotas
web reutilizem a mesma lógica de negócio já existente no projeto.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver
from backend.services.storage_path_service import resolve_default_data_file
from backend.utils.fetcher import Fetcher
from backend.web.routes_dashboard import router as dashboard_router


def create_app() -> FastAPI:
    """
    Responsabilidade:
        Criar e configurar a aplicação FastAPI com serviços e rotas.

    Parâmetros:
        Nenhum.

    Retorno:
        Instância de FastAPI pronta para execução com Uvicorn/TestClient.

    Contexto de uso:
        Função factory para facilitar testes e bootstrap de produção.
    """

    app = FastAPI(title="Product SKU Resolver")

    # Decisão técnica:
    # Centralizamos a criação dos serviços no bootstrap para permitir reuso
    # entre API REST e dashboard sem re-instanciar dependências por requisição.
    storage_path = resolve_default_data_file("products.json")
    product_store_service = ProductStoreService(storage_file_path=storage_path)
    product_resolver = ProductResolver(
        product_store=product_store_service,
        fetcher=Fetcher(),
    )

    app.state.product_store_service = product_store_service
    app.state.product_resolver = product_resolver

    app.include_router(dashboard_router)
    app.mount("/dashboard/static", StaticFiles(directory="backend/web/static"), name="static")

    return app


app = create_app()
