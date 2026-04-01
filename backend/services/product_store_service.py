"""
Serviço de persistência de produtos em arquivo JSON.

Este módulo implementa a primeira camada de storage para permitir evolução
futura para banco de dados sem quebrar regras de negócio da aplicação.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from backend.models.product import ProductRecord

logger = logging.getLogger(__name__)


class ProductStoreService:
    """
    Responsabilidade:
        Encapsular acesso ao armazenamento de produtos com operações CRUD básicas.

    Parâmetros:
        storage_file_path: Caminho do arquivo JSON de persistência.

    Retorno:
        Instância de serviço pronta para ler/escrever produtos.

    Contexto de uso:
        Usado pela camada resolver e pela camada API para consultar, inserir e
        atualizar produtos sem conhecer detalhes de IO em arquivo.
    """

    def __init__(self, storage_file_path: Path) -> None:
        """
        Responsabilidade:
            Inicializar serviço de armazenamento e garantir arquivo válido.

        Parâmetros:
            storage_file_path: Caminho para arquivo de produtos em JSON.

        Retorno:
            Nenhum.

        Contexto de uso:
            Chamado no bootstrap da aplicação; cria arquivo vazio quando ainda
            não existe para reduzir falhas na primeira execução.
        """

        self.storage_file_path = storage_file_path
        self._ensure_storage_exists()

    def _ensure_storage_exists(self) -> None:
        """
        Responsabilidade:
            Garantir existência do diretório e do arquivo JSON base.

        Parâmetros:
            Nenhum.

        Retorno:
            Nenhum.

        Contexto de uso:
            Método interno de robustez para evitar erros de arquivo ausente em
            ambientes novos ou pipelines de CI/CD.
        """

        self.storage_file_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.storage_file_path.exists():
            # Decisão técnica:
            # Inicializamos com lista vazia para manter contrato simples e
            # evitar necessidade de tratamento especial no carregamento.
            self.storage_file_path.write_text("[]", encoding="utf-8")

    def _read_all(self) -> List[ProductRecord]:
        """
        Responsabilidade:
            Ler todos os produtos do armazenamento com validação de schema.

        Parâmetros:
            Nenhum.

        Retorno:
            Lista de ProductRecord validados.

        Contexto de uso:
            Base para operações de listagem, busca por alias e atualização.
        """

        try:
            content = self.storage_file_path.read_text(encoding="utf-8")
            raw_items = json.loads(content)
        except json.JSONDecodeError as error:
            raise ValueError("Arquivo de produtos contém JSON inválido") from error
        except OSError as error:
            raise RuntimeError("Falha ao ler arquivo de produtos") from error

        if not isinstance(raw_items, list):
            raise ValueError("Arquivo de produtos deve conter uma lista JSON")

        products: List[ProductRecord] = []
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                raise ValueError("Cada produto no JSON deve ser um objeto")
            products.append(ProductRecord.from_dict(raw_item))

        return products

    def _write_all(self, products: List[ProductRecord]) -> None:
        """
        Responsabilidade:
            Persistir todos os produtos com escrita atômica simplificada.

        Parâmetros:
            products: Lista completa de produtos a ser gravada.

        Retorno:
            Nenhum.

        Contexto de uso:
            Método interno chamado por upsert/update para manter consistência
            do arquivo após operações de mutação.
        """

        payload = [product.to_dict() for product in products]
        temporary_file = self.storage_file_path.with_suffix(".tmp")

        try:
            temporary_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file.replace(self.storage_file_path)
        except OSError as error:
            raise RuntimeError("Falha ao salvar arquivo de produtos") from error

    def list_products(self) -> List[ProductRecord]:
        """
        Responsabilidade:
            Retornar todos os produtos registrados no armazenamento.

        Parâmetros:
            Nenhum.

        Retorno:
            Lista de ProductRecord.

        Contexto de uso:
            Usado por endpoints de listagem e por jobs de atualização em lote.
        """

        return self._read_all()

    def get_by_alias(self, product_alias: str) -> Optional[ProductRecord]:
        """
        Responsabilidade:
            Buscar um produto específico pelo alias canônico.

        Parâmetros:
            product_alias: Identificador textual único do produto.

        Retorno:
            ProductRecord quando encontrado, senão None.

        Contexto de uso:
            Chamado antes de atualização individual para validar existência do
            item e carregar seu estado atual.
        """

        normalized_alias = product_alias.strip()
        products = self._read_all()

        for product in products:
            if product.alias == normalized_alias:
                return product

        return None

    def upsert_product(self, product_to_save: ProductRecord) -> ProductRecord:
        """
        Responsabilidade:
            Inserir produto novo ou atualizar registro existente pelo alias.

        Parâmetros:
            product_to_save: Produto validado a ser persistido.

        Retorno:
            O mesmo ProductRecord persistido.

        Contexto de uso:
            Operação central para cadastro via API e atualizações de resolver.
        """

        normalized_product = self._ensure_page_family_sku(product_to_save)
        products = self._read_all()
        updated_products: List[ProductRecord] = []
        has_replaced_existing = False

        for current_product in products:
            if current_product.alias == normalized_product.alias:
                updated_products.append(normalized_product)
                has_replaced_existing = True
            else:
                updated_products.append(current_product)

        if not has_replaced_existing:
            updated_products.append(normalized_product)

        self._write_all(updated_products)
        persisted_product = self._confirm_persisted_product(normalized_product.alias)
        logger.info("Produto persistido com sucesso: alias=%s arquivo=%s", persisted_product.alias, self.storage_file_path)
        return persisted_product

    def replace_product(self, current_alias: str, updated_product: ProductRecord) -> ProductRecord:
        """
        Responsabilidade:
            Substituir um produto existente permitindo alteracao de alias.

        Parametros:
            current_alias: Alias atual do registro que deve ser substituido.
            updated_product: Novo estado completo do produto apos edicao.

        Retorno:
            ProductRecord persistido com os dados atualizados.

        Contexto de uso:
            Utilizado pela tela de edicao quando o operador altera identidade
            estavel ou decide renomear o alias do produto.
        """

        normalized_current_alias = current_alias.strip()
        if not normalized_current_alias:
            raise KeyError("Alias atual nao pode ser vazio para substituir produto")

        normalized_updated_product = self._ensure_page_family_sku(updated_product)
        products = self._read_all()
        updated_products: List[ProductRecord] = []
        has_replaced_existing = False

        for current_product in products:
            if current_product.alias == normalized_current_alias:
                updated_products.append(normalized_updated_product)
                has_replaced_existing = True
            else:
                updated_products.append(current_product)

        if not has_replaced_existing:
            raise KeyError(f"Produto com alias '{normalized_current_alias}' nao encontrado")

        self._write_all(updated_products)
        persisted_product = self._confirm_persisted_product(normalized_updated_product.alias)
        logger.info("Produto atualizado com sucesso: alias=%s arquivo=%s", persisted_product.alias, self.storage_file_path)
        return persisted_product

    def _confirm_persisted_product(self, product_alias: str) -> ProductRecord:
        """
        Responsabilidade:
            Confirmar que um produto realmente ficou gravado apos a escrita.

        Parametros:
            product_alias: Alias do registro que acabou de ser persistido.

        Retorno:
            ProductRecord relido do storage persistente.

        Contexto de uso:
            Evita sucesso falso no fluxo de cadastro, garantindo a etapa de
            read-after-write antes de responder para a interface.
        """

        persisted_product = self.get_by_alias(product_alias)
        if persisted_product is None:
            raise RuntimeError(
                f"Falha de persistencia: o produto '{product_alias}' nao foi encontrado apos a gravacao"
            )

        return persisted_product

    def _ensure_page_family_sku(self, product: ProductRecord) -> ProductRecord:
        """
        Responsabilidade:
            Garantir que o produto carregue o identificador estável da página.

        Parametros:
            product: Produto que será persistido no storage.

        Retorno:
            ProductRecord com `page_family_sku` preenchido quando possível.

        Contexto de uso:
            Centraliza a regra de retrocompatibilidade para que cadastro, edição
            e update automático compartilhem a mesma derivação do SKU estável.
        """

        if product.page_family_sku:
            return product

        return ProductRecord(
            alias=product.alias,
            brand=product.brand,
            name=product.name,
            variant=product.variant,
            last_known_url=product.last_known_url,
            last_known_sku=product.last_known_sku,
            page_family_sku=ProductRecord.from_dict(product.to_dict()).page_family_sku,
            parent_reference=product.parent_reference,
            source_type=product.source_type,
            concentration=product.concentration,
            shelf_reference_label=product.shelf_reference_label,
            notes=product.notes,
            image_url=product.image_url,
            stock_qty=product.stock_qty,
            variant_notes=product.variant_notes,
            is_active=product.is_active,
            shelf_number=product.shelf_number,
            display_order=product.display_order,
        )

    def delete_product(self, product_alias: str) -> ProductRecord:
        """
        Responsabilidade:
            Remover um produto existente do armazenamento pelo alias informado.

        Parametros:
            product_alias: Alias canônico do produto que deve ser excluído.

        Retorno:
            ProductRecord removido, para que a camada chamadora possa limpar
            estados auxiliares relacionados ao item.

        Contexto de uso:
            Utilizado pelo dashboard quando o operador decide retirar um item do
            catálogo operacional sem afetar os demais registros persistidos.
        """

        normalized_alias = product_alias.strip()
        if not normalized_alias:
            raise KeyError("Alias nao pode ser vazio para exclusao de produto")

        products = self._read_all()
        remaining_products: List[ProductRecord] = []
        removed_product: Optional[ProductRecord] = None

        for current_product in products:
            if current_product.alias == normalized_alias:
                removed_product = current_product
                continue
            remaining_products.append(current_product)

        if removed_product is None:
            raise KeyError(f"Produto com alias '{normalized_alias}' nao encontrado")

        self._write_all(remaining_products)
        return removed_product

    def update_product_sku_and_url(
        self,
        product_alias: str,
        new_sku: str,
        new_url: str,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Atualizar SKU e URL de um produto já existente no armazenamento.

        Parâmetros:
            product_alias: Alias do produto alvo da atualização.
            new_sku: SKU recém-extraído e validado pela camada de resolução.
            new_url: URL onde o SKU válido foi encontrado.

        Retorno:
            ProductRecord atualizado e persistido.

        Contexto de uso:
            Chamado após validação de identidade e extração de SKU no pipeline
            de resolução, mantendo dados mutáveis sempre sincronizados.
        """

        existing_product = self.get_by_alias(product_alias)
        if existing_product is None:
            raise KeyError(f"Produto com alias '{product_alias}' não encontrado")

        updated_product = ProductRecord(
            alias=existing_product.alias,
            brand=existing_product.brand,
            name=existing_product.name,
            variant=existing_product.variant,
            last_known_url=new_url.strip(),
            last_known_sku=new_sku.strip(),
            page_family_sku=existing_product.page_family_sku,
            parent_reference=existing_product.parent_reference,
            source_type=existing_product.source_type,
            concentration=existing_product.concentration,
            shelf_reference_label=existing_product.shelf_reference_label,
            notes=existing_product.notes,
            image_url=existing_product.image_url,
            stock_qty=existing_product.stock_qty,
            variant_notes=existing_product.variant_notes,
            is_active=existing_product.is_active,
            shelf_number=existing_product.shelf_number,
            display_order=existing_product.display_order,
        )

        self.upsert_product(updated_product)
        return updated_product
