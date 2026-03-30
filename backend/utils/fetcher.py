"""
Utilitário de download de páginas HTML.

Este módulo centraliza regras de requisição HTTP para evitar duplicação de
configuração em camadas superiores e facilitar testes/mocks no futuro.
"""

from __future__ import annotations

from dataclasses import dataclass
from socket import timeout as SocketTimeout
from typing import Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


@dataclass(slots=True)
class FetchResult:
    """
    Responsabilidade:
        Representar resultado normalizado de uma tentativa de download.

    Parâmetros:
        final_url: URL final retornada após eventuais redirecionamentos.
        status_code: Código HTTP retornado pelo servidor.
        html_content: Conteúdo HTML bruto da resposta.

    Retorno:
        Estrutura tipada para consumo por parser e resolver.

    Contexto de uso:
        Mantém contrato explícito entre fetcher e próximas etapas da pipeline.
    """

    final_url: str
    status_code: int
    html_content: str


class Fetcher:
    """
    Responsabilidade:
        Executar requisições HTTP com timeout e cabeçalhos previsíveis.

    Parâmetros:
        default_timeout_seconds: Tempo máximo de espera por resposta.
        user_agent: User-Agent padrão para reduzir bloqueios triviais.

    Retorno:
        Instância de cliente HTTP reutilizável.

    Contexto de uso:
        Utilizado pelo resolver para baixar páginas de produto antes da extração.
    """

    def __init__(self, default_timeout_seconds: float = 8.0, user_agent: str = "ProductSkuResolver/1.0") -> None:
        """
        Responsabilidade:
            Configurar parâmetros padrão de requisição para o cliente HTTP.

        Parâmetros:
            default_timeout_seconds: Timeout default em segundos por requisição.
            user_agent: Valor de User-Agent enviado ao servidor remoto.

        Retorno:
            Nenhum.

        Contexto de uso:
            Inicializado uma vez e reutilizado para manter consistência nas
            chamadas de fetch sem depender de bibliotecas externas.
        """

        self.default_timeout_seconds = default_timeout_seconds
        self.user_agent = user_agent

    def fetch_page(self, target_url: str, extra_headers: Optional[Dict[str, str]] = None) -> FetchResult:
        """
        Responsabilidade:
            Baixar conteúdo HTML de uma URL com tratamento de erro explícito.

        Parâmetros:
            target_url: URL da página que será consultada.
            extra_headers: Cabeçalhos adicionais específicos de varejista.

        Retorno:
            FetchResult com URL final, status HTTP e HTML da resposta.

        Contexto de uso:
            Primeira etapa do pipeline de resolução; falhas aqui devem ser
            reportadas de forma clara para permitir fallback do orquestrador.
        """

        sanitized_url = target_url.strip()
        if not sanitized_url:
            raise ValueError("A URL informada para fetch está vazia")

        parsed_url = urlparse(sanitized_url)
        if not parsed_url.scheme or not parsed_url.netloc:
            raise ValueError(f"URL inválida para fetch: {sanitized_url}")

        request_headers: Dict[str, str] = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if extra_headers:
            request_headers.update(extra_headers)

        request = Request(url=sanitized_url, headers=request_headers, method="GET")

        try:
            with urlopen(request, timeout=self.default_timeout_seconds) as response:
                html_content = response.read().decode("utf-8", errors="replace")
                final_url = response.geturl()
                status_code = getattr(response, "status", 200)
        except TimeoutError as error:
            raise RuntimeError(
                f"Timeout ao buscar URL após {self.default_timeout_seconds:.0f}s: {sanitized_url}"
            ) from error
        except SocketTimeout as error:
            raise RuntimeError(
                f"Timeout ao buscar URL após {self.default_timeout_seconds:.0f}s: {sanitized_url}"
            ) from error
        except HTTPError as error:
            raise RuntimeError(f"HTTP {error.code} ao buscar URL: {sanitized_url}") from error
        except URLError as error:
            raise RuntimeError(f"Falha de rede ao buscar URL: {sanitized_url}") from error

        return FetchResult(final_url=final_url, status_code=status_code, html_content=html_content)
