"""
Testes do comportamento de cache dos assets estaticos do dashboard.
"""

from __future__ import annotations

from pathlib import Path

from starlette.responses import Response

from backend.services.shelf_banner_service import ShelfBannerService
from backend.web.static_files import DashboardStaticFiles


def test_shelf_banner_service_gera_url_versionada_estavel() -> None:
    """
    Responsabilidade:
        Garantir que a URL publica do banner seja estavel entre renders.

    Parametros:
        Nenhum.

    Retorno:
        Nenhum; valida a URL versionada devolvida pelo servico visual.

    Contexto de uso:
        Protege o cache `immutable` no navegador, assegurando que o app use a
        mesma URL do banner ate que o arquivo real seja alterado no projeto.
    """

    service = ShelfBannerService(static_directory=Path("backend/web/static"))
    visual = service.get_visual(shelf_number=1, shelf_title="Perfumes Arabes")

    first_public_url = service.build_public_image_url(visual)
    second_public_url = service.build_public_image_url(visual)

    assert first_public_url == second_public_url
    assert first_public_url.startswith("/dashboard/static/shelf-banners/shelf-01-perfumes-arabes.png?v=")


def test_dashboard_static_files_aplica_cache_forte_nos_banners() -> None:
    """
    Responsabilidade:
        Garantir que banners de prateleira recebam cache HTTP agressivo.

    Parametros:
        Nenhum.

    Retorno:
        Nenhum; valida o header `Cache-Control` aplicado ao asset.

    Contexto de uso:
        Sem esse header, o navegador tende a revalidar os banners ao voltar
        para a Home, o que causa flicker e sensacao de recarregamento.
    """

    static_files = DashboardStaticFiles(directory="backend/web/static")
    response = Response()

    static_files._apply_cache_headers(
        response=response,
        request_path="/dashboard/static/shelf-banners/shelf-01-perfumes-arabes.png",
    )

    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"


def test_dashboard_static_files_aplica_cache_moderado_nos_assets_de_marca() -> None:
    """
    Responsabilidade:
        Garantir que icones e arquivos de marca tenham cache reutilizavel.

    Parametros:
        Nenhum.

    Retorno:
        Nenhum; valida a politica de cache dos assets de branding.

    Contexto de uso:
        Mantem favicons e icones reaproveitaveis sem forcar cache eterno, ja
        que esses arquivos podem mudar mais que os banners da perfumaria.
    """

    static_files = DashboardStaticFiles(directory="backend/web/static")
    response = Response()

    static_files._apply_cache_headers(
        response=response,
        request_path="/dashboard/static/brand/favicon.svg",
    )

    assert response.headers["Cache-Control"] == "public, max-age=604800, stale-while-revalidate=86400"
