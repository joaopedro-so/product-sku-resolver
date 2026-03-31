"""
Modelos de domínio relacionados ao produto monitorado.

Este módulo concentra o contrato de dados usado pelo armazenamento e pelas
camadas de serviço, mantendo validações simples e explícitas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict


@dataclass(slots=True)
class ProductRecord:
    """
    Responsabilidade:
        Representar um produto com identidade estável e dados mutáveis.

    Parâmetros:
        alias: Identificador interno amigável para API e armazenamento.
        brand: Marca estável usada em validações de correspondência.
        name: Nome estável do produto usado em validações de correspondência.
        variant: Variante estável (ex.: volume, cor, tamanho).
        last_known_url: URL mais recente considerada válida para o produto.
        last_known_sku: Código operacional mais recente da variante selecionada.
        page_family_sku: Identificador estável da página/produto pai.

    Retorno:
        Instância tipada de ProductRecord para uso interno no backend.

    Contexto de uso:
        Utilizada por product_store_service para leitura e escrita em JSON,
        garantindo contrato único de dados em toda a aplicação.
    """

    alias: str
    brand: str
    name: str
    variant: str
    last_known_url: str
    last_known_sku: str
    page_family_sku: str = ""
    shelf_number: int | None = None
    display_order: int | None = None

    @classmethod
    def from_dict(cls, source: Dict[str, Any]) -> "ProductRecord":
        """
        Responsabilidade:
            Criar ProductRecord a partir de dicionário com validação mínima.

        Parâmetros:
            source: Dicionário bruto vindo de JSON, API ou outro adaptador.

        Retorno:
            ProductRecord devidamente normalizado para uso interno.

        Contexto de uso:
            Chamado na leitura do arquivo de produtos para transformar dados
            não tipados em estrutura confiável antes das regras de negócio.
        """

        required_keys = [
            "alias",
            "brand",
            "name",
            "variant",
            "last_known_url",
            "last_known_sku",
        ]

        missing_keys = [key for key in required_keys if key not in source]
        if missing_keys:
            missing_description = ", ".join(missing_keys)
            raise ValueError(
                f"Registro de produto inválido: campos ausentes: {missing_description}"
            )

        normalized_url = str(source["last_known_url"]).strip()

        # Decisão técnica:
        # Forçamos string para reduzir inconsistência de tipos vindos de JSON
        # ou payloads externos, simplificando as camadas seguintes.
        return cls(
            alias=str(source["alias"]).strip(),
            brand=str(source["brand"]).strip(),
            name=str(source["name"]).strip(),
            variant=str(source["variant"]).strip(),
            last_known_url=normalized_url,
            last_known_sku=str(source["last_known_sku"]).strip(),
            page_family_sku=_resolve_page_family_sku(
                raw_page_family_sku=source.get("page_family_sku"),
                last_known_url=normalized_url,
            ),
            shelf_number=_optional_to_int(source.get("shelf_number")),
            display_order=_optional_to_int(source.get("display_order")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Responsabilidade:
            Serializar ProductRecord para formato dicionário persistível.

        Parâmetros:
            Nenhum.

        Retorno:
            Dicionário com os campos que devem ser gravados no armazenamento.

        Contexto de uso:
            Utilizado na persistência em products.json ou retorno de API,
            mantendo formato consistente para integrações externas.
        """

        payload: Dict[str, Any] = {
            "alias": self.alias,
            "brand": self.brand,
            "name": self.name,
            "variant": self.variant,
            "last_known_url": self.last_known_url,
            "last_known_sku": self.last_known_sku,
            "page_family_sku": self.page_family_sku,
        }
        if self.shelf_number is not None:
            payload["shelf_number"] = self.shelf_number
        if self.display_order is not None:
            payload["display_order"] = self.display_order
        return payload

    @property
    def variant_code(self) -> str:
        """
        Responsabilidade:
            Expor o código operacional da variante com nome semântico claro.

        Parâmetros:
            Nenhum.

        Retorno:
            Código atualmente usado para operação, barcode e conferência.

        Contexto de uso:
            Ajuda a separar mentalmente o código da variante do identificador
            estável da página, sem quebrar compatibilidade com o storage atual.
        """

        return self.last_known_sku


def _optional_to_int(raw_value: Any) -> int | None:
    """
    Responsabilidade:
        Normalizar um valor opcional para inteiro de forma resiliente.

    Parâmetros:
        raw_value: Valor bruto vindo de JSON ou formulário.

    Retorno:
        Inteiro quando houver conteúdo válido; caso contrário, None.

    Contexto de uso:
        Mantém compatibilidade com produtos antigos que ainda não tinham
        localização de prateleira persistida.
    """

    if raw_value in (None, ""):
        return None

    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _resolve_page_family_sku(raw_page_family_sku: Any, last_known_url: str) -> str:
    """
    Responsabilidade:
        Resolver o identificador estável da página a partir do dado persistido
        ou da URL conhecida quando o campo ainda não existir no JSON.

    Parâmetros:
        raw_page_family_sku: Valor bruto opcional vindo do storage.
        last_known_url: URL usada como fallback para derivar o SKU da página.

    Retorno:
        Identificador estável do produto pai, ou string vazia.

    Contexto de uso:
        Mantém retrocompatibilidade com registros antigos enquanto introduz a
        separação entre SKU da página e código operacional da variante.
    """

    normalized_page_family_sku = str(raw_page_family_sku or "").strip()
    if normalized_page_family_sku:
        return normalized_page_family_sku

    url_match = re.search(r"/A-(\d+)-", str(last_known_url), flags=re.IGNORECASE)
    if url_match:
        return url_match.group(1).strip()

    return ""
