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
from backend.services.product_draft_service import ProductDraftService
from backend.services.product_store_service import ProductStoreService
from backend.services.resolver import ProductResolver, ResolveResult
from backend.utils.barcode import build_code128_svg_data_uri
from backend.utils.fetcher import FetchResult, Fetcher
from backend.utils.parser import PageData, parse_page_data

router = APIRouter(prefix="/dashboard", tags=["dashboard-web"])
templates = Jinja2Templates(directory="backend/web/templates")
templates.env.globals["build_code128_svg_data_uri"] = build_code128_svg_data_uri

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


def _build_product_visual_snapshot(request: Request, product: ProductRecord) -> Optional[PageData]:
    """
    Responsabilidade:
        Buscar imagem e metadados visuais do produto para o dashboard.

    Parâmetros:
        request: Requisição atual para acesso ao resolver e ao fetcher.
        product: Produto persistido que terá a URL atual consultada.

    Retorno:
        PageData com sinais visuais da página, ou None em caso de falha.

    Contexto de uso:
        Utilizada na tela de detalhe para exibir imagem do produto e manter a
        experiência operacional mais próxima de uma etiqueta visual.
    """

    resolver_service = _get_resolver_service(request)
    fetcher = getattr(resolver_service, "fetcher", None)
    if fetcher is None or not product.last_known_url.strip():
        return None

    try:
        fetch_result: FetchResult = fetcher.fetch_page(product.last_known_url)
    except Exception:
        # Tratamento de erro:
        # A prévia visual não pode derrubar a tela de detalhe; quando o fetch
        # falha, mantemos o restante da interface funcional com placeholder.
        return None

    return parse_page_data(
        page_url=fetch_result.final_url,
        html_content=fetch_result.html_content,
        configured_fallback_sku=product.last_known_sku,
    )


def _get_fetcher_service(request: Request) -> Optional[Fetcher]:
    """
    Responsabilidade:
        Recuperar o fetcher compartilhado usado pelas rotas web.

    Parametros:
        request: Requisicao HTTP atual com acesso ao app state.

    Retorno:
        Instancia de Fetcher quando disponivel; caso contrario, None.

    Contexto de uso:
        Necessario para gerar rascunhos automaticos a partir de uma URL.
    """

    resolver_service = _get_resolver_service(request)
    fetcher = getattr(resolver_service, "fetcher", None)
    if fetcher is not None:
        return fetcher

    runtime_services = getattr(request.app.state, "services", None)
    return getattr(runtime_services, "fetcher", None)


def _build_new_product_form_context(
    submitted_data: Optional[Dict[str, str]] = None,
    error_message: Optional[str] = None,
    autofill_message: Optional[str] = None,
    autofill_error_message: Optional[str] = None,
    autofill_preview: Optional[Dict[str, Any]] = None,
    form_mode: str = "create",
    form_action_url: str = "/dashboard/products",
    submit_button_label: str = "Salvar produto",
    cancel_url: str = "/dashboard",
) -> Dict[str, Any]:
    """
    Responsabilidade:
        Padronizar o contexto da tela de cadastro manual e automatico.

    Parametros:
        submitted_data: Valores atuais do formulario para re-renderizacao.
        error_message: Erro de validacao ao salvar o cadastro final.
        autofill_message: Mensagem de sucesso do preenchimento automatico.
        autofill_error_message: Erro ocorrido ao montar o rascunho automatico.
        autofill_preview: Dados auxiliares extraidos da pagina para exibicao.
        form_mode: Modo visual do formulario (`create` ou `edit`).
        form_action_url: Endpoint que recebera o submit final do formulario.
        submit_button_label: Texto do botao principal de salvamento.
        cancel_url: Destino do CTA secundario ao cancelar a operacao.

    Retorno:
        Dicionario compativel com o template `add_product.html`.

    Contexto de uso:
        Evita duplicacao de estrutura entre o fluxo manual e o assistido por URL.
    """

    return {
        "error_message": error_message,
        "submitted_data": submitted_data or {},
        "autofill_message": autofill_message,
        "autofill_error_message": autofill_error_message,
        "autofill_preview": autofill_preview,
        "form_mode": form_mode,
        "form_action_url": form_action_url,
        "submit_button_label": submit_button_label,
        "cancel_url": cancel_url,
    }


def _build_submitted_data_from_product(product: ProductRecord) -> Dict[str, str]:
    """
    Responsabilidade:
        Converter ProductRecord em payload pronto para preencher formulario.

    Parametros:
        product: Produto persistido que sera exibido para edicao.

    Retorno:
        Dicionario com os campos esperados pelo template de formulario.

    Contexto de uso:
        Reaproveitado pelo fluxo de edicao para evitar mapear campos manualmente.
    """

    return {
        "alias": product.alias,
        "brand": product.brand,
        "name": product.name,
        "variant": product.variant,
        "last_known_url": product.last_known_url,
        "last_known_sku": product.last_known_sku,
    }


def _validate_alias_availability(
    product_store: ProductStoreService,
    desired_alias: str,
    current_alias: Optional[str] = None,
) -> Optional[str]:
    """
    Responsabilidade:
        Validar se o alias desejado esta livre para criacao ou edicao.

    Parametros:
        product_store: Storage usado para consultar aliases existentes.
        desired_alias: Alias informado pelo operador no formulario.
        current_alias: Alias atual do produto em edicao, quando houver.

    Retorno:
        Mensagem de erro quando houver colisao; caso contrario, None.

    Contexto de uso:
        Evita sobrescrita silenciosa de outro produto ao salvar o formulario.
    """

    normalized_desired_alias = desired_alias.strip()
    existing_product = product_store.get_by_alias(normalized_desired_alias)
    if existing_product is None:
        return None

    normalized_current_alias = str(current_alias or "").strip()
    if normalized_current_alias and existing_product.alias == normalized_current_alias:
        return None

    return f"Ja existe um produto cadastrado com o alias '{normalized_desired_alias}'."


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
        context=_build_new_product_form_context(),
    )


@router.post("/products/auto-fill")
async def dashboard_autofill_product_form(request: Request) -> Any:
    """
    Responsabilidade:
        Preencher automaticamente o formulario de produto a partir de uma URL.

    Parametros:
        request: Requisicao HTTP com a URL enviada pelo usuario.

    Retorno:
        TemplateResponse com o formulario preenchido ou erro explicavel.

    Contexto de uso:
        Reduz digitacao manual no cadastro sem salvar o produto imediatamente.
    """

    form_data = await request.form()
    last_known_url = str(form_data.get("last_known_url", "")).strip()
    fetcher = _get_fetcher_service(request)

    if fetcher is None:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context=_build_new_product_form_context(
                submitted_data={"last_known_url": last_known_url},
                autofill_error_message="Nao foi possivel inicializar o servico de leitura da URL.",
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    product_store = _get_store_service(request)
    draft_service = ProductDraftService(fetcher=fetcher, product_store=product_store)
    draft_result = draft_service.build_from_url(last_known_url)

    if not draft_result.success or draft_result.draft is None:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context=_build_new_product_form_context(
                submitted_data={"last_known_url": last_known_url},
                autofill_error_message=draft_result.message,
                autofill_preview=asdict(draft_result.page_data) if draft_result.page_data else None,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    return templates.TemplateResponse(
        request=request,
        name="add_product.html",
        context=_build_new_product_form_context(
            submitted_data={
                "alias": draft_result.draft.alias,
                "brand": draft_result.draft.brand,
                "name": draft_result.draft.name,
                "variant": draft_result.draft.variant,
                "last_known_url": draft_result.draft.last_known_url,
                "last_known_sku": draft_result.draft.last_known_sku,
            },
            autofill_message=draft_result.message,
            autofill_preview={
                "title": draft_result.draft.source_title,
                "image_url": draft_result.draft.image_url,
                "sku": draft_result.draft.last_known_sku,
                "url": draft_result.draft.last_known_url,
            },
        ),
    )


@router.get("/products/{alias}/edit")
def dashboard_edit_product_form(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Exibir formulario de edicao para um produto ja cadastrado.

    Parametros:
        request: Requisicao HTTP usada na renderizacao do template.
        alias: Alias atual do produto que sera editado.

    Retorno:
        TemplateResponse com dados preenchidos ou erro 404 renderizado.

    Contexto de uso:
        Fluxo manual de manutencao quando o operador precisa corrigir cadastro.
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
                "error_message": "Produto nao encontrado para edicao.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    return templates.TemplateResponse(
        request=request,
        name="add_product.html",
        context=_build_new_product_form_context(
            submitted_data=_build_submitted_data_from_product(product),
            form_mode="edit",
            form_action_url=f"/dashboard/products/{alias}/edit",
            submit_button_label="Salvar alteracoes",
            cancel_url=f"/dashboard/products/{alias}",
        ),
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
            "product_preview": _build_product_visual_snapshot(request, product),
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
    last_known_sku = str(form_data.get("last_known_sku", "")).strip() or "unknown"
    alias_conflict_message = _validate_alias_availability(product_store, alias)

    if alias_conflict_message:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context=_build_new_product_form_context(
                submitted_data={
                    "alias": alias,
                    "brand": brand,
                    "name": name,
                    "variant": variant,
                    "last_known_url": last_known_url,
                    "last_known_sku": last_known_sku,
                },
                error_message=alias_conflict_message,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

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
                "last_known_sku": last_known_sku,
            }
        )
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context=_build_new_product_form_context(
                submitted_data={
                    "alias": alias,
                    "brand": brand,
                    "name": name,
                    "variant": variant,
                    "last_known_url": last_known_url,
                    "last_known_sku": last_known_sku,
                },
                error_message=f"Dados invalidos para cadastro: {error}",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    product_store.upsert_product(new_product)
    return RedirectResponse(url="/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/products/{alias}/edit")
async def dashboard_edit_product(request: Request, alias: str) -> Any:
    """
    Responsabilidade:
        Validar e persistir alteracoes manuais de um produto existente.

    Parametros:
        request: Requisicao HTTP atual com o formulario de edicao.
        alias: Alias atual do produto antes da alteracao.

    Retorno:
        Redirecionamento para detalhe em sucesso, ou formulario com erro.

    Contexto de uso:
        Permite corrigir identidade, alias, URL e SKU inicial no dashboard.
    """

    product_store = _get_store_service(request)
    existing_product = product_store.get_by_alias(alias)

    if existing_product is None:
        return templates.TemplateResponse(
            request=request,
            name="product_detail.html",
            context={
                "product": None,
                "alias": alias,
                "last_update": None,
                "error_message": "Produto nao encontrado para edicao.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    form_data = await request.form()
    updated_alias = str(form_data.get("alias", "")).strip()
    brand = str(form_data.get("brand", "")).strip()
    name = str(form_data.get("name", "")).strip()
    variant = str(form_data.get("variant", "")).strip()
    last_known_url = str(form_data.get("last_known_url", "")).strip()
    last_known_sku = str(form_data.get("last_known_sku", "")).strip() or "unknown"
    submitted_data = {
        "alias": updated_alias,
        "brand": brand,
        "name": name,
        "variant": variant,
        "last_known_url": last_known_url,
        "last_known_sku": last_known_sku,
    }

    alias_conflict_message = _validate_alias_availability(
        product_store=product_store,
        desired_alias=updated_alias,
        current_alias=alias,
    )
    if alias_conflict_message:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context=_build_new_product_form_context(
                submitted_data=submitted_data,
                error_message=alias_conflict_message,
                form_mode="edit",
                form_action_url=f"/dashboard/products/{alias}/edit",
                submit_button_label="Salvar alteracoes",
                cancel_url=f"/dashboard/products/{alias}",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        updated_product = ProductRecord.from_dict(submitted_data)
    except ValueError as error:
        return templates.TemplateResponse(
            request=request,
            name="add_product.html",
            context=_build_new_product_form_context(
                submitted_data=submitted_data,
                error_message=f"Dados invalidos para edicao: {error}",
                form_mode="edit",
                form_action_url=f"/dashboard/products/{alias}/edit",
                submit_button_label="Salvar alteracoes",
                cancel_url=f"/dashboard/products/{alias}",
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    product_store.replace_product(current_alias=alias, updated_product=updated_product)

    if alias != updated_alias and alias in last_update_by_alias:
        # Decisao tecnica:
        # Quando o alias muda, migramos o ultimo status em memoria para manter
        # coerencia visual na tela de detalhe sem depender de persistencia extra.
        last_update_by_alias[updated_alias] = last_update_by_alias.pop(alias)

    return RedirectResponse(
        url=f"/dashboard/products/{updated_product.alias}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


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
