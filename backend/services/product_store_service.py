"""
Serviço de persistência de produtos em arquivo JSON.

Este módulo implementa a primeira camada de storage para permitir evolução
futura para banco de dados sem quebrar regras de negócio da aplicação.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import RLock
from typing import List, Optional

from backend.models.product import ProductRecord
from backend.services.datetime_service import get_current_utc_isoformat
from backend.services.matcher import normalize_variant
from backend.services.product_reconciliation_service import (
    ProductReconciliationService,
    ReconciliationDecision,
)

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

    def __init__(
        self,
        storage_file_path: Path,
        reconciliation_service: Optional[ProductReconciliationService] = None,
    ) -> None:
        """
        Responsabilidade:
            Inicializar serviço de armazenamento e garantir arquivo válido.

        Parâmetros:
            storage_file_path: Caminho para arquivo de produtos em JSON.
            reconciliation_service: Serviço opcional responsável por religar
                itens manuais a produtos que voltaram ao site.

        Retorno:
            Nenhum.

        Contexto de uso:
            Chamado no bootstrap da aplicação; cria arquivo vazio quando ainda
            não existe para reduzir falhas na primeira execução.
        """

        self.storage_file_path = storage_file_path
        self.reconciliation_service = reconciliation_service or ProductReconciliationService()
        self._storage_lock = RLock()
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

        with self._storage_lock:
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
        with self._storage_lock:
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

        with self._storage_lock:
            normalized_product = self._ensure_page_family_sku(product_to_save)
            products = self._read_all()
            linked_target = self._find_linked_target_for_site_product(
                incoming_site_product=normalized_product,
                existing_products=products,
            )
            if linked_target is not None:
                linked_product = self._build_refreshed_linked_product(
                    current_product=linked_target,
                    incoming_site_product=normalized_product,
                )
                updated_products = self._replace_product_by_alias(
                    products=products,
                    target_alias=linked_target.alias,
                    replacement_product=linked_product,
                    discarded_alias=normalized_product.alias,
                )
                self._write_all(updated_products)
                persisted_product = self._confirm_persisted_product(linked_product.alias)
                logger.info(
                    "Produto de site reconciliado com registro ja vinculado: alias=%s arquivo=%s",
                    persisted_product.alias,
                    self.storage_file_path,
                )
                return persisted_product

            reconciliation_decision = self.reconciliation_service.decide_site_link(
                incoming_site_product=normalized_product,
                existing_products=products,
            )
            reconciled_product = self._apply_reconciliation_decision(
                current_products=products,
                incoming_site_product=normalized_product,
                reconciliation_decision=reconciliation_decision,
            )
            if reconciled_product is not None:
                return reconciled_product

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

        with self._storage_lock:
            products = self._read_all()
            current_product = self._find_product_by_alias(products, normalized_current_alias)
            if current_product is None:
                raise KeyError(f"Produto com alias '{normalized_current_alias}' nao encontrado")

            normalized_updated_product = self._ensure_page_family_sku(
                self._preserve_existing_site_metadata(
                    current_product=current_product,
                    updated_product=updated_product,
                )
            )
            updated_products: List[ProductRecord] = []

            for current_product in products:
                if current_product.alias == normalized_current_alias:
                    updated_products.append(normalized_updated_product)
                else:
                    updated_products.append(current_product)

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

        return self._build_product_from_payload(
            base_product=product,
            payload_updates={
                "page_family_sku": ProductRecord.from_dict(product.to_dict()).page_family_sku,
            },
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

        with self._storage_lock:
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
        site_variant_id: str = "",
    ) -> ProductRecord:
        """
        Responsabilidade:
            Atualizar SKU, URL e vínculo de variante de um produto existente.

        Parâmetros:
            product_alias: Alias do produto alvo da atualização.
            new_sku: SKU recém-extraído e validado pela camada de resolução.
            new_url: URL onde o SKU válido foi encontrado.
            site_variant_id: Identificador estável da variante no site quando
                disponível no HTML, como `data-aggkey`.

        Retorno:
            ProductRecord atualizado e persistido.

        Contexto de uso:
            Chamado após validação de identidade e extração de SKU no pipeline
            de resolução, mantendo dados mutáveis e o vínculo da variante
            sincronizados sem perder a identidade interna do alias.
        """

        with self._storage_lock:
            existing_product = self.get_by_alias(product_alias)
            if existing_product is None:
                raise KeyError(f"Produto com alias '{product_alias}' não encontrado")

            updated_product = ProductRecord(
                alias=existing_product.alias,
                brand=existing_product.brand,
                name=existing_product.display_name,
                variant=existing_product.variant,
                last_known_url=new_url.strip(),
                last_known_sku=new_sku.strip(),
                match_name=existing_product.match_name,
                line_name=existing_product.line_name,
                normalized_match_name=existing_product.normalized_match_name,
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
                site_link_status="linked_to_site",
                site_product_id=existing_product.site_product_id or existing_product.page_family_sku,
                site_candidate_id="",
                match_confidence=existing_product.match_confidence,
                match_signals=existing_product.match_signals,
                site_candidate_url="",
                site_candidate_code="",
                site_candidate_variant_id="",
                current_site_code=new_sku.strip(),
                current_barcode_value=new_sku.strip(),
                last_matched_at=_build_site_link_timestamp(),
                site_variant_id=site_variant_id.strip() or existing_product.site_variant_id,
            )

            return self.upsert_product(updated_product)

    def confirm_site_candidate(self, product_alias: str) -> ProductRecord:
        """
        Responsabilidade:
            Confirmar manualmente um candidato do site para um item interno.

        Parametros:
            product_alias: Alias do produto que possui uma correspondencia pendente.

        Retorno:
            ProductRecord persistido ja marcado como vinculado ao site.

        Contexto de uso:
            Usado pelo dashboard quando o operador reconhece que o item manual
            realmente voltou ao site e quer retomar a sincronizacao normal.
        """

        with self._storage_lock:
            products = self._read_all()
            current_product = self._find_product_by_alias(products, product_alias)
            if current_product is None:
                raise KeyError(f"Produto com alias '{product_alias}' nao encontrado")

            if not current_product.has_site_candidate:
                raise ValueError("O produto informado nao possui candidato de vinculo pendente")

            updated_product = self._build_product_from_payload(
                base_product=current_product,
                payload_updates={
                    "last_known_url": current_product.site_candidate_url or current_product.last_known_url,
                    "last_known_sku": current_product.site_candidate_code or current_product.last_known_sku,
                    "page_family_sku": current_product.page_family_sku or current_product.site_candidate_id,
                    "site_link_status": "linked_to_site",
                    "site_product_id": current_product.site_candidate_id or current_product.site_product_id,
                    "site_candidate_id": "",
                    "site_candidate_url": "",
                    "site_candidate_code": "",
                    "site_candidate_variant_id": "",
                    "last_matched_at": _build_site_link_timestamp(),
                    "site_variant_id": current_product.site_candidate_variant_id or current_product.site_variant_id,
                    "current_site_code": current_product.site_candidate_code or current_product.current_site_code or current_product.last_known_sku,
                    "current_barcode_value": current_product.site_candidate_code or current_product.current_barcode_value or current_product.last_known_sku,
                },
            )

            self._write_all(
                self._replace_product_by_alias(
                    products=products,
                    target_alias=current_product.alias,
                    replacement_product=updated_product,
                )
            )
            return self._confirm_persisted_product(updated_product.alias)

    def ignore_site_candidate(self, product_alias: str) -> ProductRecord:
        """
        Responsabilidade:
            Limpar uma sugestao de vinculo que o operador decidiu ignorar.

        Parametros:
            product_alias: Alias do produto com candidato salvo no catalogo.

        Retorno:
            ProductRecord persistido ja sem estado de candidato pendente.

        Contexto de uso:
            Permite descartar correspondencias medias sem perder o cadastro
            manual existente nem deixar a interface presa em alerta eterno.
        """

        with self._storage_lock:
            products = self._read_all()
            current_product = self._find_product_by_alias(products, product_alias)
            if current_product is None:
                raise KeyError(f"Produto com alias '{product_alias}' nao encontrado")

            if not current_product.has_site_candidate:
                raise ValueError("O produto informado nao possui candidato de vinculo pendente")

            updated_product = self._build_product_from_payload(
                base_product=current_product,
                payload_updates={
                    "site_link_status": "manual_unlinked",
                    "site_candidate_id": "",
                    "site_candidate_url": "",
                    "site_candidate_code": "",
                    "site_candidate_variant_id": "",
                    "match_confidence": None,
                    "match_signals": [],
                    "last_matched_at": "",
                },
            )

            self._write_all(
                self._replace_product_by_alias(
                    products=products,
                    target_alias=current_product.alias,
                    replacement_product=updated_product,
                )
            )
            return self._confirm_persisted_product(updated_product.alias)

    def _apply_reconciliation_decision(
        self,
        current_products: List[ProductRecord],
        incoming_site_product: ProductRecord,
        reconciliation_decision: ReconciliationDecision,
    ) -> Optional[ProductRecord]:
        """
        Responsabilidade:
            Aplicar no storage a decisao produzida pela camada de reconciliacao.

        Parametros:
            current_products: Lista atual do catalogo antes da nova gravacao.
            incoming_site_product: Variante recem-chegada do site.
            reconciliation_decision: Acao segura decidida pelo reconciliador.

        Retorno:
            ProductRecord persistido quando a decisao consumir o item; caso
            contrario, None para que o fluxo siga no upsert normal por alias.

        Contexto de uso:
            Isola o efeito de `candidate_found` e `linked_to_site` em um unico
            ponto, evitando que a regra de nao duplicar fique espalhada.
        """

        if reconciliation_decision.decision_type not in {"linked_to_site", "candidate_found"}:
            return None

        target_product = self._find_product_by_alias(
            products=current_products,
            product_alias=reconciliation_decision.target_alias,
        )
        if target_product is None:
            return None

        if reconciliation_decision.decision_type == "linked_to_site":
            replacement_product = self.reconciliation_service.build_linked_product(
                current_product=target_product,
                incoming_site_product=incoming_site_product,
                confidence=reconciliation_decision.confidence,
                match_signals=reconciliation_decision.match_signals,
            )
        else:
            replacement_product = self.reconciliation_service.build_candidate_product(
                current_product=target_product,
                incoming_site_product=incoming_site_product,
                confidence=reconciliation_decision.confidence,
                match_signals=reconciliation_decision.match_signals,
            )

        updated_products = self._replace_product_by_alias(
            products=current_products,
            target_alias=target_product.alias,
            replacement_product=replacement_product,
            discarded_alias=incoming_site_product.alias,
        )
        self._write_all(updated_products)
        persisted_product = self._confirm_persisted_product(replacement_product.alias)
        logger.info(
            "Reconciliacao aplicada com sucesso: alias=%s decisao=%s arquivo=%s",
            persisted_product.alias,
            reconciliation_decision.decision_type,
            self.storage_file_path,
        )
        return persisted_product

    def _find_linked_target_for_site_product(
        self,
        incoming_site_product: ProductRecord,
        existing_products: List[ProductRecord],
    ) -> Optional[ProductRecord]:
        """
        Responsabilidade:
            Encontrar um registro ja vinculado ao site que representa a mesma variante.

        Parametros:
            incoming_site_product: Variante atual recebida do fluxo do site.
            existing_products: Catalogo inteiro carregado do storage.

        Retorno:
            ProductRecord existente quando o item ja estiver vinculado; senao None.

        Contexto de uso:
            Evita que um produto manual, depois de religado ao site, volte a
            duplicar no catalogo em futuras importacoes ou atualizacoes.
        """

        if incoming_site_product.source_type != "site":
            return None

        resolved_site_product_id = incoming_site_product.site_product_id or incoming_site_product.page_family_sku
        normalized_variant = normalize_variant(incoming_site_product.variant)
        normalized_site_variant_id = incoming_site_product.site_variant_id.strip()

        # Decisao tecnica:
        # Essa reconciliacao de "item ja vinculado" so pode acontecer quando o
        # site traz um identificador estavel do produto pai ou da propria
        # variante. Sem isso, preferimos nao deduplicar para evitar mesclas
        # indevidas entre perfumes diferentes com o mesmo volume.
        if not resolved_site_product_id and not normalized_site_variant_id:
            return None

        for current_product in existing_products:
            if current_product.site_link_status != "linked_to_site":
                continue

            if resolved_site_product_id:
                current_site_product_id = current_product.site_product_id or current_product.page_family_sku
                if current_site_product_id != resolved_site_product_id:
                    continue

            if normalized_site_variant_id and current_product.site_variant_id:
                if current_product.site_variant_id == normalized_site_variant_id:
                    return current_product

            if normalized_variant and normalize_variant(current_product.variant) == normalized_variant:
                return current_product

        return None

    def _build_refreshed_linked_product(
        self,
        current_product: ProductRecord,
        incoming_site_product: ProductRecord,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Atualizar um item ja vinculado ao site preservando identidade interna.

        Parametros:
            current_product: Registro persistido que deve continuar sendo o mesmo item.
            incoming_site_product: Dados recem-observados no site para a variante.

        Retorno:
            ProductRecord pronto para substituir o registro atual no storage.

        Contexto de uso:
            Mantem alias, prateleira, estoque e historico local enquanto os
            campos operacionais do site seguem sendo atualizados normalmente.
        """

        return self._build_product_from_payload(
            base_product=current_product,
            payload_updates={
                "brand": current_product.brand or incoming_site_product.brand,
                "name": current_product.display_name or incoming_site_product.display_name,
                "match_name": current_product.match_name or incoming_site_product.effective_match_name,
                "line_name": current_product.line_name or incoming_site_product.line_name,
                "normalized_match_name": current_product.normalized_match_name or incoming_site_product.normalized_match_name,
                "variant": current_product.variant or incoming_site_product.variant,
                "last_known_url": incoming_site_product.last_known_url,
                "last_known_sku": incoming_site_product.last_known_sku,
                "page_family_sku": incoming_site_product.page_family_sku,
                "concentration": current_product.concentration or incoming_site_product.concentration,
                "image_url": current_product.image_url or incoming_site_product.image_url,
                "site_link_status": "linked_to_site",
                "site_product_id": incoming_site_product.site_product_id or incoming_site_product.page_family_sku,
                "site_candidate_id": "",
                "site_candidate_url": "",
                "site_candidate_code": "",
                "site_candidate_variant_id": "",
                "site_variant_id": incoming_site_product.site_variant_id,
                "last_matched_at": _build_site_link_timestamp(),
                "current_site_code": incoming_site_product.last_known_sku,
                "current_barcode_value": incoming_site_product.variant_code,
            },
        )

    def _preserve_existing_site_metadata(
        self,
        current_product: ProductRecord,
        updated_product: ProductRecord,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Preservar metadados de vinculo ao editar um produto ja persistido.

        Parametros:
            current_product: Registro existente antes da edicao manual.
            updated_product: Novo estado enviado pelo formulario.

        Retorno:
            ProductRecord enriquecido com os metadados que nao devem sumir.

        Contexto de uso:
            Evita que uma simples edicao de nome, notas ou prateleira apague o
            estado de reconciliacao ou o vinculo ja retomado com o site.
        """

        if updated_product.source_type == "site":
            normalized_site_link_status = "linked_to_site"
        elif current_product.site_link_status in {"candidate_found", "linked_to_site"}:
            normalized_site_link_status = current_product.site_link_status
        else:
            normalized_site_link_status = "manual_unlinked"

        return self._build_product_from_payload(
            base_product=updated_product,
            payload_updates={
                "page_family_sku": updated_product.page_family_sku or current_product.page_family_sku,
                "site_link_status": normalized_site_link_status,
                "site_product_id": current_product.site_product_id,
                "site_candidate_id": current_product.site_candidate_id,
                "site_candidate_url": current_product.site_candidate_url,
                "site_candidate_code": current_product.site_candidate_code,
                "site_candidate_variant_id": current_product.site_candidate_variant_id,
                "match_confidence": current_product.match_confidence,
                "match_signals": current_product.match_signals or [],
                "last_matched_at": current_product.last_matched_at,
                "site_variant_id": current_product.site_variant_id,
                "current_site_code": current_product.current_site_code if updated_product.source_type != "site" else updated_product.last_known_sku,
                "current_barcode_value": updated_product.last_known_sku,
            },
        )

    def _replace_product_by_alias(
        self,
        products: List[ProductRecord],
        target_alias: str,
        replacement_product: ProductRecord,
        discarded_alias: str = "",
    ) -> List[ProductRecord]:
        """
        Responsabilidade:
            Substituir um alias alvo e descartar um alias redundante se necessario.

        Parametros:
            products: Lista atual carregada do storage.
            target_alias: Alias que deve ser substituido.
            replacement_product: Novo registro que ocupara o lugar do alvo.
            discarded_alias: Alias redundante que deve ser removido do resultado.

        Retorno:
            Nova lista de produtos pronta para persistencia.

        Contexto de uso:
            Centraliza a regra de nao duplicar itens quando o fluxo recebe uma
            variante do site que na pratica representa um cadastro interno ja existente.
        """

        updated_products: List[ProductRecord] = []
        normalized_discarded_alias = discarded_alias.strip()

        for current_product in products:
            if current_product.alias == target_alias:
                updated_products.append(replacement_product)
                continue

            if normalized_discarded_alias and current_product.alias == normalized_discarded_alias:
                continue

            updated_products.append(current_product)

        return updated_products

    def _find_product_by_alias(
        self,
        products: List[ProductRecord],
        product_alias: str,
    ) -> Optional[ProductRecord]:
        """
        Responsabilidade:
            Localizar rapidamente um produto dentro de uma colecao ja carregada.

        Parametros:
            products: Lista de produtos previamente lida do storage.
            product_alias: Alias procurado dentro da colecao.

        Retorno:
            ProductRecord correspondente quando existir; senao None.

        Contexto de uso:
            Evita releitura desnecessaria do arquivo em fluxos internos do store.
        """

        normalized_alias = product_alias.strip()
        for product in products:
            if product.alias == normalized_alias:
                return product
        return None

    def _build_product_from_payload(
        self,
        base_product: ProductRecord,
        payload_updates: dict,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Recriar um ProductRecord preservando compatibilidade com o schema atual.

        Parametros:
            base_product: Produto usado como base para gerar o novo payload.
            payload_updates: Campos que devem sobrescrever o estado original.

        Retorno:
            ProductRecord reidratado via `from_dict` com os updates aplicados.

        Contexto de uso:
            Evita esquecer campos novos do modelo ao reconstruir registros em
            operacoes de edicao, reconciliacao e refresh de vinculo.
        """

        payload = base_product.to_dict()
        payload.update(payload_updates)
        return ProductRecord.from_dict(payload)


def _build_site_link_timestamp() -> str:
    """
    Responsabilidade:
        Gerar timestamp ISO8601 para auditoria de confirmacao manual.

    Parametros:
        Nenhum.

    Retorno:
        Texto ISO8601 em UTC com o instante atual.

    Contexto de uso:
        Mantem o historico de reconciliacao consistente entre auto-link e
        vinculacao manual confirmada pelo operador.
    """

    return get_current_utc_isoformat()
