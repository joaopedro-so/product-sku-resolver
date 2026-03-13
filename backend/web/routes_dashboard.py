"""
Rotas do dashboard web para operação manual do resolvedor de SKU.

Este módulo mantém a camada web separada da API REST, reutilizando os
serviços existentes para evitar duplicação de regras de negócio.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver, ResolveResult

router = APIRouter(prefix="/dashboard", tags=["dashboard-web"])
templates = Jinja2Templates(directory="backend/web/templates")

# Decisão técnica:
# Armazenamos em memória o último resultado de atualização por alias para
# exibir feedback operacional rápido sem alterar o schema atual do storage.
last_update_by_alias: Dict[str, Dict[str, Any]] = {}


def _get_store_service(request: Request) -> ProductStoreService:
    """
    Responsabilidade:
        Obter instância compartilhada do serviço de armazenamento no app state.

    Parâmetros:
        request: Requisição HTTP atual para acessar `request.app.state`.

    Retorno:
        Instância de ProductStoreService previamente inicializada no bootstrap.

    Contexto de uso:
        Utilizada por todas as rotas web para centralizar o acesso ao storage.
    """

    return request.app.state.product_store_service


def _get_resolver_service(request: Request) -> ProductResolver:
    """
    Responsabilidade:
        Obter instância compartilhada do resolvedor no app state.

    Parâmetros:
        request: Requisição HTTP atual para acessar `request.app.state`.

    Retorno:
        Instância de ProductResolver previamente inicializada no bootstrap.

    Contexto de uso:
        Utilizada por rotas de atualização para acionar o pipeline completo.
    """

    return request.app.state.product_resolver


def _build_update_snapshot(resolve_result: ResolveResult) -> Dict[str, Any]:
    """
    Responsabilidade:
        Converter resultado de resolução em estrutura serializável para template.

    Parâmetros:
        resolve_result: Resultado retornado por `resolve_sku_for_alias`.

    Retorno:
        Dicionário com campos de status, mensagem e dados de match/page.

    Contexto de uso:
        Padroniza os dados exibidos no dashboard e na tela de detalhe.
    """

    return {
        "success": resolve_result.success,
        "message": resolve_result.message,
        "error_code": resolve_result.error_code,
        "page_data": asdict(resolve_result.page_data) if resolve_result.page_data else None,
        "match_result": asdict(resolve_result.match_result)
        if resolve_result.match_result
        else None,
    }


@router.get("")
def dashboard_home(request: Request) -> Any:
    """
    Responsabilidade:
        Renderizar página principal do dashboard com lista de produtos.

    Parâmetros:
        request: Requisição HTTP para renderização do template Jinja2.

    Retorno:
        TemplateResponse com tabela operacional e ações de atualização.

    Contexto de uso:
        Página de entrada para operação diária de monitoramento de SKUs.
    """

    product_store = _get_store_service(request)
    products = product_store.list_products()

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "products": products,
            "last_update_by_alias": last_update_by_alias,
        },
    )


@router.get("/products/new")
def dashboard_new_product_form(request: Request) -> Any:
    """
    Responsabilidade:
        Exibir formulário de cadastro de novo produto no dashboard.

    Parâmetros:
        request: Requisição HTTP usada na renderização do template.

    Retorno:
        TemplateResponse com formulário vazio e mensagens opcionais.

    Contexto de uso:
        Fluxo web de cadastro manual sem necessidade de cliente externo.
    """

    return templates.TemplateResponse(
        request=request,
        name="add_product.html",
        context={"error_message": None, "submitted_data": {}},
    )


@router.get("/products/{alias}")
def dashboard_product_detail(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Mostrar detalhes de um produto e último status de atualização.

    Parâmetros:
        request: Requisição HTTP para renderização.
        alias: Identificador único do produto no storage.

    Retorno:
        TemplateResponse com detalhes do produto ou erro 404 renderizado.

    Contexto de uso:
        Página de inspeção operacional para diagnóstico de resolução.
    """

    product_store = _get_store_service(request)
    product = product_store.get_by_alias(alias)

    if product is None:
        return templates.TemplateResponse(
            request=request,
            name="product_detail.html",
            context={
                "product": None,
                "alias": alias,
                "last_update": None,
                "error_message": "Produto não encontrado para o alias informado.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return templates.TemplateResponse(
        request=request,
        name="product_detail.html",
        context={
            "product": product,
            "alias": alias,
            "last_update": last_update_by_alias.get(alias),
            "error_message": None,
        },
    )


@router.post("/products")
async def dashboard_create_product(request: Request) -> Any:
    """
    Responsabilidade:
        Validar e criar produto via formulário HTML do dashboard.

    Parâmetros:
        request: Requisição HTTP atual.
        alias: Alias único do produto.
        brand: Marca esperada para validação de identidade.
        name: Nome base do produto.
        variant: Variante (volume, tamanho, etc.).
        last_known_url: URL inicial para primeira resolução.

    Retorno:
        Redirecionamento para dashboard em sucesso, ou formulário com erro.

    Contexto de uso:
        Permite cadastro operacional sem duplicar regras no frontend.
    """

    product_store = _get_store_service(request)

    # Tratamento de entrada:
    # Usamos `request.form()` para aceitar submissão HTML tradicional sem
    # depender de validação de Form do FastAPI (que exigiria dependência extra).
    form_data = await request.form()
    alias = str(form_data.get("alias", "")).strip()
    brand = str(form_data.get("brand", "")).strip()
    name = str(form_data.get("name", "")).strip()
    variant = str(form_data.get("variant", "")).strip()
    last_known_url = str(form_data.get("last_known_url", "")).strip()

    try:
        # Decisão técnica:
        # Reutilizamos `ProductRecord.from_dict` para concentrar validação do
        # contrato de domínio em um único ponto e evitar regras divergentes.
        new_product = ProductRecord.from_dict(
            {
                "alias": alias,
                "brand": brand,
                "name": name,
                "variant": variant,
                "last_known_url": last_known_url,
                "last_known_sku": "unknown",
            }
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context={
                "error_message": f"Dados inválidos para cadastro: {error}",
                "submitted_data": {
                    "alias": alias,
                    "brand": brand,
                    "name": name,
                    "variant": variant,
                    "last_known_url": last_known_url,
                },
            },
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    product_store.upsert_product(new_product)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/products/{alias}/update")
def dashboard_update_product(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Executar atualização manual de SKU para um produto específico.

    Parâmetros:
        request: Requisição HTTP atual.
        alias: Alias do produto a ser processado pelo resolver.

    Retorno:
        Redirecionamento para tela de detalhe com status atualizado.

    Contexto de uso:
        Ação por linha da tabela e também da página de detalhe.
    """

    resolver_service = _get_resolver_service(request)
    resolve_result = resolver_service.resolve_sku_for_alias(alias)
    last_update_by_alias[alias] = _build_update_snapshot(resolve_result)

    return RedirectResponse(
        url=f"/dashboard/products/{alias}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.post("/update-all")
def dashboard_update_all_products(request: Request) -> Any:
    """
    Responsabilidade:
        Disparar atualização de todos os produtos cadastrados no storage.

    Parâmetros:
        request: Requisição HTTP atual para obter serviços compartilhados.

    Retorno:
        Redirecionamento para dashboard principal após processamento em lote.

    Contexto de uso:
        Ação global para operação manual quando se deseja forçar refresh geral.
    """

    product_store = _get_store_service(request)
    resolver_service = _get_resolver_service(request)

    for product in product_store.list_products():
        # Tratamento de erro:
        # O resolver já encapsula exceções em ResolveResult; portanto, aqui só
        # registramos cada saída para exibição posterior no dashboard.
        resolve_result = resolver_service.resolve_sku_for_alias(product.alias)
        last_update_by_alias[product.alias] = _build_update_snapshot(resolve_result)

    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)
