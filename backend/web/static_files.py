"""
Infraestrutura de assets estaticos do dashboard web.

Este modulo isola regras de cache HTTP para assets quase imutaveis, como os
banners das prateleiras, sem misturar essa preocupacao com as rotas de negocio.
"""

from __future__ import annotations

from typing import Any

from fastapi.staticfiles import StaticFiles
from starlette.responses import Response


class DashboardStaticFiles(StaticFiles):
    """
    Responsabilidade:
        Servir assets estaticos do dashboard com politicas de cache adequadas.

    Parametros:
        *args: Parametros posicionais repassados para `StaticFiles`.
        **kwargs: Parametros nomeados repassados para `StaticFiles`.

    Retorno:
        Instancia de `StaticFiles` com regras adicionais de cache.

    Contexto de uso:
        Banners de prateleira e icones de marca mudam muito raramente. Sem um
        `Cache-Control` forte, o navegador tende a revalidar essas imagens a
        cada retorno para a Home, o que causa a sensacao de recarregamento.
    """

    def file_response(
        self,
        full_path: str,
        stat_result: Any,
        scope: dict[str, Any],
        status_code: int = 200,
    ) -> Response:
        """
        Responsabilidade:
            Aplicar headers de cache depois que o arquivo estatico e resolvido.

        Parametros:
            full_path: Caminho absoluto do arquivo estatico no disco.
            stat_result: Metadados de sistema do arquivo solicitado.
            scope: Scope ASGI da requisicao atual.
            status_code: Codigo HTTP inicial da resposta do arquivo.

        Retorno:
            `Response` final com os headers adequados ao tipo de asset.

        Contexto de uso:
            Mantem o comportamento padrao do Starlette para ETag e
            Last-Modified, mas acrescenta uma politica forte para assets
            visuais quase imutaveis do app.
        """

        response = super().file_response(
            full_path=full_path,
            stat_result=stat_result,
            scope=scope,
            status_code=status_code,
        )
        request_path = str(scope.get("path", "") or "") if isinstance(scope, dict) else ""
        self._apply_cache_headers(response=response, request_path=request_path)
        return response

    def _apply_cache_headers(self, response: Response, request_path: str) -> None:
        """
        Responsabilidade:
            Escolher a politica de cache correta para cada familia de asset.

        Parametros:
            response: Resposta estatica ja criada pelo framework.
            request_path: Caminho publico solicitado pelo navegador.

        Retorno:
            Nenhum.

        Contexto de uso:
            Centraliza a regra de expiracao para facilitar manutencao futura e
            evitar cabeçalhos inconsistentes entre ambientes.
        """

        normalized_request_path = str(request_path or "").strip()
        if normalized_request_path.startswith("/dashboard/static/shelf-banners/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return

        if normalized_request_path.startswith("/dashboard/static/brand/"):
            response.headers["Cache-Control"] = "public, max-age=604800, stale-while-revalidate=86400"
