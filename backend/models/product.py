"""
Modelos de domínio relacionados ao produto monitorado.

Este módulo concentra o contrato de dados usado pelo armazenamento e pelas
camadas de serviço, mantendo validações simples e explícitas.
"""

from __future__ import annotations

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
        last_known_sku: SKU mais recente aceito após validação de identidade.

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

        # Decisão técnica:
        # Forçamos string para reduzir inconsistência de tipos vindos de JSON
        # ou payloads externos, simplificando as camadas seguintes.
        return cls(
            alias=str(source["alias"]).strip(),
            brand=str(source["brand"]).strip(),
            name=str(source["name"]).strip(),
            variant=str(source["variant"]).strip(),
            last_known_url=str(source["last_known_url"]).strip(),
            last_known_sku=str(source["last_known_sku"]).strip(),
        )

    def to_dict(self) -> Dict[str, str]:
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

        return {
            "alias": self.alias,
            "brand": self.brand,
            "name": self.name,
            "variant": self.variant,
            "last_known_url": self.last_known_url,
            "last_known_sku": self.last_known_sku,
        }
