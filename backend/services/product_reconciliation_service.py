"""
Servico de reconciliacao entre cadastros internos e produtos que voltam ao site.

Este modulo compara produtos `manual` ou `legacy` com registros `site`
posteriormente importados, permitindo retomar sincronizacao sem criar
duplicatas no catalogo operacional.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from backend.models.product import ProductRecord
from backend.services.matcher import normalize_text, normalize_variant
from backend.services.site_link_override_service import (
    SiteLinkOverrideDefinition,
    SiteLinkOverrideService,
)

AUTO_LINK_THRESHOLD = 0.92
CANDIDATE_THRESHOLD = 0.74
AMBIGUITY_GAP_THRESHOLD = 0.05

GENERIC_NAME_TOKENS = {
    "perfume",
    "masculino",
    "feminino",
    "unissex",
    "eau",
    "de",
    "toilette",
    "parfum",
    "edp",
    "edt",
}


@dataclass(slots=True)
class ReconciliationDecision:
    """
    Responsabilidade:
        Representar a decisão final de reconciliação para um produto do site.

    Parâmetros:
        decision_type: Resultado semântico da análise (`none`, `candidate_found` ou `linked_to_site`).
        target_alias: Alias interno que deve receber o vínculo, quando existir.
        confidence: Confiança numérica da decisão tomada.
        match_signals: Sinais e justificativas registrados para auditoria.
        site_product_id: Identificador pai do site envolvido na decisão.

    Retorno:
        Estrutura simples e explícita consumida pelo storage.

    Contexto de uso:
        Permite que a camada de persistência aplique o efeito correto da
        reconciliação sem precisar conhecer detalhes do algoritmo de matching.
    """

    decision_type: str
    target_alias: str = ""
    confidence: float | None = None
    match_signals: List[str] | None = None
    site_product_id: str = ""


@dataclass(slots=True)
class _CandidateScore:
    """
    Responsabilidade:
        Transportar score e sinais de um candidato interno durante a análise.

    Parâmetros:
        product: Produto interno analisado como possível alvo.
        score: Pontuação final calculada para o vínculo.
        signals: Lista de sinais positivos ou negativos relevantes.
        is_exact_structured_match: Indica se a coincidência é forte e explícita.

    Retorno:
        Estrutura interna usada apenas dentro do reconciliador.

    Contexto de uso:
        Facilita a comparação entre múltiplos candidatos sem espalhar variáveis
        soltas pela implementação do serviço.
    """

    product: ProductRecord
    score: float
    signals: List[str]
    is_exact_structured_match: bool


class ProductReconciliationService:
    """
    Responsabilidade:
        Decidir se um produto vindo do site deve vincular, sugerir candidato ou ignorar.

    Parâmetros:
        override_service: Camada opcional de overrides manuais de vínculo.

    Retorno:
        Serviço pronto para análise de reconciliação.

    Contexto de uso:
        Chamado pelo storage antes de persistir novos produtos `site`, evitando
        que itens manuais reaparecidos gerem duplicatas no catálogo.
    """

    def __init__(
        self,
        override_service: Optional[SiteLinkOverrideService] = None,
    ) -> None:
        """
        Responsabilidade:
            Inicializar dependências configuráveis da reconciliação.

        Parâmetros:
            override_service: Serviço opcional de overrides manuais.

        Retorno:
            Nenhum.

        Contexto de uso:
            Permite injetar configurações específicas nos testes sem acoplar a
            reconciliação a um único arquivo físico de configuração.
        """

        self.override_service = override_service or SiteLinkOverrideService()

    def decide_site_link(
        self,
        incoming_site_product: ProductRecord,
        existing_products: List[ProductRecord],
    ) -> ReconciliationDecision:
        """
        Responsabilidade:
            Determinar se o produto do site deve vincular a um item interno existente.

        Parâmetros:
            incoming_site_product: Variante recém-importada a partir do site.
            existing_products: Catálogo atual persistido antes da nova gravação.

        Retorno:
            ReconciliationDecision com a ação segura a ser executada.

        Contexto de uso:
            Executado no momento do `upsert` para impedir duplicatas quando um
            perfume manual volta a existir no site futuramente.
        """

        if incoming_site_product.source_type != "site":
            return ReconciliationDecision(decision_type="none")

        override_target = self._match_override_target(
            incoming_site_product=incoming_site_product,
            existing_products=existing_products,
        )
        if override_target is not None:
            return ReconciliationDecision(
                decision_type="linked_to_site",
                target_alias=override_target.alias,
                confidence=1.0,
                match_signals=["Override manual de vínculo aplicado"],
                site_product_id=self._resolve_site_product_id(incoming_site_product),
            )

        eligible_products = self._filter_reconcilable_products(existing_products)
        candidate_scores = [
            self._score_candidate(incoming_site_product, existing_product)
            for existing_product in eligible_products
        ]
        candidate_scores = [candidate for candidate in candidate_scores if candidate is not None]
        if not candidate_scores:
            return ReconciliationDecision(decision_type="none")

        sorted_candidates = sorted(candidate_scores, key=lambda candidate: candidate.score, reverse=True)
        best_candidate = sorted_candidates[0]
        second_candidate = sorted_candidates[1] if len(sorted_candidates) > 1 else None
        if self._is_ambiguous(best_candidate, second_candidate):
            return ReconciliationDecision(decision_type="none")

        if best_candidate.is_exact_structured_match or best_candidate.score >= AUTO_LINK_THRESHOLD:
            return ReconciliationDecision(
                decision_type="linked_to_site",
                target_alias=best_candidate.product.alias,
                confidence=round(best_candidate.score, 4),
                match_signals=best_candidate.signals,
                site_product_id=self._resolve_site_product_id(incoming_site_product),
            )

        if best_candidate.score >= CANDIDATE_THRESHOLD:
            return ReconciliationDecision(
                decision_type="candidate_found",
                target_alias=best_candidate.product.alias,
                confidence=round(best_candidate.score, 4),
                match_signals=best_candidate.signals,
                site_product_id=self._resolve_site_product_id(incoming_site_product),
            )

        return ReconciliationDecision(decision_type="none")

    def build_linked_product(
        self,
        current_product: ProductRecord,
        incoming_site_product: ProductRecord,
        confidence: float | None,
        match_signals: List[str] | None,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Construir a nova versão vinculada do produto interno existente.

        Parâmetros:
            current_product: Registro interno que deve manter sua identidade.
            incoming_site_product: Dados mais recentes observados no site.
            confidence: Confiança da reconciliação aplicada.
            match_signals: Sinais de auditoria produzidos no matching.

        Retorno:
            ProductRecord pronto para substituir o item interno no storage.

        Contexto de uso:
            Garante que o alias, a prateleira e o histórico local continuem os
            mesmos, enquanto apenas o vínculo e o código do site são retomados.
        """

        return ProductRecord(
            alias=current_product.alias,
            brand=current_product.brand or incoming_site_product.brand,
            name=current_product.name or incoming_site_product.name,
            variant=current_product.variant or incoming_site_product.variant,
            last_known_url=incoming_site_product.last_known_url,
            last_known_sku=incoming_site_product.last_known_sku,
            page_family_sku=incoming_site_product.page_family_sku,
            parent_reference=current_product.parent_reference or incoming_site_product.parent_reference,
            source_type=current_product.source_type,
            concentration=current_product.concentration or incoming_site_product.concentration,
            shelf_reference_label=current_product.shelf_reference_label,
            notes=current_product.notes,
            image_url=current_product.image_url or incoming_site_product.image_url,
            stock_qty=current_product.stock_qty,
            variant_notes=current_product.variant_notes,
            is_active=current_product.is_active,
            shelf_number=current_product.shelf_number,
            display_order=current_product.display_order,
            site_link_status="linked_to_site",
            site_product_id=self._resolve_site_product_id(incoming_site_product),
            site_candidate_id="",
            match_confidence=confidence,
            match_signals=match_signals or [],
            last_matched_at=_build_match_timestamp(),
            site_variant_id=incoming_site_product.site_variant_id,
            current_site_code=incoming_site_product.last_known_sku,
            current_barcode_value=incoming_site_product.variant_code,
        )

    def build_candidate_product(
        self,
        current_product: ProductRecord,
        incoming_site_product: ProductRecord,
        confidence: float | None,
        match_signals: List[str] | None,
    ) -> ProductRecord:
        """
        Responsabilidade:
            Construir a nova versão do produto interno marcada como candidato.

        Parâmetros:
            current_product: Registro interno que receberá o estado de candidato.
            incoming_site_product: Dados do produto do site considerado provável.
            confidence: Confiança estimada da correspondência.
            match_signals: Sinais de auditoria produzidos no matching.

        Retorno:
            ProductRecord preservando o código manual atual, mas com candidato salvo.

        Contexto de uso:
            Evita auto-link arriscado sem perder a informação de que o perfume
            pode ter voltado ao site e merece revisão posterior.
        """

        return ProductRecord(
            alias=current_product.alias,
            brand=current_product.brand,
            name=current_product.name,
            variant=current_product.variant,
            last_known_url=current_product.last_known_url,
            last_known_sku=current_product.last_known_sku,
            page_family_sku=current_product.page_family_sku,
            parent_reference=current_product.parent_reference,
            source_type=current_product.source_type,
            concentration=current_product.concentration,
            shelf_reference_label=current_product.shelf_reference_label,
            notes=current_product.notes,
            image_url=current_product.image_url,
            stock_qty=current_product.stock_qty,
            variant_notes=current_product.variant_notes,
            is_active=current_product.is_active,
            shelf_number=current_product.shelf_number,
            display_order=current_product.display_order,
            site_link_status="candidate_found",
            site_product_id=current_product.site_product_id,
            site_candidate_id=self._resolve_site_product_id(incoming_site_product),
            match_confidence=confidence,
            match_signals=match_signals or [],
            last_matched_at=_build_match_timestamp(),
            site_variant_id=current_product.site_variant_id,
            current_site_code=current_product.current_site_code,
            current_barcode_value=current_product.current_barcode_value or current_product.last_known_sku,
        )

    def _match_override_target(
        self,
        incoming_site_product: ProductRecord,
        existing_products: List[ProductRecord],
    ) -> Optional[ProductRecord]:
        """
        Responsabilidade:
            Encontrar um alvo interno usando overrides declarados manualmente.

        Parâmetros:
            incoming_site_product: Variante recém-importada do site.
            existing_products: Catálogo interno atual.

        Retorno:
            ProductRecord alvo quando houver override compatível; senão None.

        Contexto de uso:
            Garante que a curadoria manual tenha precedência total sobre as
            heurísticas automáticas da reconciliação.
        """

        site_product_id = self._resolve_site_product_id(incoming_site_product)
        normalized_variant = normalize_variant(incoming_site_product.variant)
        normalized_code = str(incoming_site_product.last_known_sku).strip()

        for override_definition in self.override_service.list_overrides():
            if override_definition.site_product_id and override_definition.site_product_id != site_product_id:
                continue

            if override_definition.site_variant_label and normalize_variant(override_definition.site_variant_label) != normalized_variant:
                continue

            if override_definition.site_variant_code and override_definition.site_variant_code != normalized_code:
                continue

            matched_product = self._find_override_target_product(
                override_definition=override_definition,
                existing_products=existing_products,
            )
            if matched_product is not None:
                return matched_product

        return None

    def _find_override_target_product(
        self,
        override_definition: SiteLinkOverrideDefinition,
        existing_products: List[ProductRecord],
    ) -> Optional[ProductRecord]:
        """
        Responsabilidade:
            Localizar o produto interno descrito por um override manual.

        Parâmetros:
            override_definition: Override manual já normalizado.
            existing_products: Catálogo persistido atual.

        Retorno:
            ProductRecord correspondente quando existir; senão None.

        Contexto de uso:
            Separa a leitura do override da busca concreta no catálogo,
            mantendo a regra explícita e fácil de testar.
        """

        for existing_product in existing_products:
            if override_definition.internal_alias and existing_product.alias == override_definition.internal_alias:
                return existing_product

            if (
                override_definition.internal_parent_reference
                and existing_product.parent_reference == override_definition.internal_parent_reference
            ):
                return existing_product

        return None

    def _filter_reconcilable_products(self, existing_products: List[ProductRecord]) -> List[ProductRecord]:
        """
        Responsabilidade:
            Selecionar apenas produtos internos elegíveis para reconciliação.

        Parâmetros:
            existing_products: Catálogo persistido atual.

        Retorno:
            Lista de variantes que podem receber vínculo futuro ao site.

        Contexto de uso:
            Evita que produtos já vinculados ao site participem novamente da
            comparação, reduzindo risco de duplicações indevidas.
        """

        return [
            existing_product
            for existing_product in existing_products
            if existing_product.source_type in {"manual", "legacy"}
            and existing_product.site_link_status != "linked_to_site"
        ]

    def _score_candidate(
        self,
        incoming_site_product: ProductRecord,
        existing_product: ProductRecord,
    ) -> Optional[_CandidateScore]:
        """
        Responsabilidade:
            Calcular a compatibilidade entre um produto do site e um item interno.

        Parâmetros:
            incoming_site_product: Variante recém-importada do site.
            existing_product: Variante manual ou legacy candidata ao vínculo.

        Retorno:
            _CandidateScore quando o candidato continuar elegível; senão None.

        Contexto de uso:
            Implementa a etapa central de matching estável, baseada em marca,
            nome, concentração e volume, sem confiar apenas no código atual.
        """

        normalized_site_brand = normalize_text(incoming_site_product.brand)
        normalized_existing_brand = normalize_text(existing_product.brand)
        if not normalized_site_brand or normalized_site_brand != normalized_existing_brand:
            return None

        site_identity = _build_identity_signature(incoming_site_product)
        existing_identity = _build_identity_signature(existing_product)
        if _has_hard_conflict(site_identity, existing_identity):
            return None

        signals = ["Marca compatível"]
        score = 0.32

        if site_identity["name_core"] == existing_identity["name_core"] and site_identity["name_core"]:
            score += 0.34
            signals.append("Nome base compatível")
            is_exact_name = True
        else:
            similarity = _calculate_token_similarity(
                site_identity["name_core"],
                existing_identity["name_core"],
            )
            if similarity < 0.65:
                return None
            score += 0.24 * similarity
            signals.append(f"Nome semelhante ({similarity:.2f})")
            is_exact_name = False

        if site_identity["product_type"] and existing_identity["product_type"]:
            score += 0.2
            signals.append("Concentração compatível")
        elif site_identity["product_type"] == existing_identity["product_type"]:
            score += 0.1
            signals.append("Sem conflito de concentração")

        if site_identity["variant"] and existing_identity["variant"] and site_identity["variant"] == existing_identity["variant"]:
            score += 0.14
            signals.append("Variante compatível")
        else:
            return None

        is_exact_structured_match = (
            is_exact_name
            and bool(site_identity["variant"])
            and site_identity["variant"] == existing_identity["variant"]
            and (
                site_identity["product_type"] == existing_identity["product_type"]
                or not site_identity["product_type"]
                or not existing_identity["product_type"]
            )
        )

        return _CandidateScore(
            product=existing_product,
            score=min(score, 1.0),
            signals=signals,
            is_exact_structured_match=is_exact_structured_match,
        )

    def _is_ambiguous(
        self,
        best_candidate: _CandidateScore,
        second_candidate: Optional[_CandidateScore],
    ) -> bool:
        """
        Responsabilidade:
            Detectar quando a melhor correspondência ainda está ambígua.

        Parâmetros:
            best_candidate: Melhor candidato encontrado na rodada atual.
            second_candidate: Segundo melhor candidato, quando existir.

        Retorno:
            True quando a diferença entre candidatos é pequena demais; senão False.

        Contexto de uso:
            Implementa a regra de segurança que impede auto-link em cenários
            onde dois itens parecem igualmente prováveis.
        """

        if second_candidate is None:
            return False

        return abs(best_candidate.score - second_candidate.score) < AMBIGUITY_GAP_THRESHOLD

    def _resolve_site_product_id(self, incoming_site_product: ProductRecord) -> str:
        """
        Responsabilidade:
            Resolver o identificador estável do produto pai do site.

        Parâmetros:
            incoming_site_product: Variante recém-importada do site.

        Retorno:
            Identificador pai estável, preferencialmente `page_family_sku`.

        Contexto de uso:
            Centraliza a referência principal do site usada no vínculo e nas
            sugestões de candidato preservadas no catálogo.
        """

        return incoming_site_product.page_family_sku or incoming_site_product.site_product_id


def _build_identity_signature(product: ProductRecord) -> dict[str, str]:
    """
    Responsabilidade:
        Extrair sinais estáveis de identidade de um produto para o matching.

    Parâmetros:
        product: Variante do catálogo ou do site a ser normalizada.

    Retorno:
        Dicionário com marca, nome-base, concentração e variante normalizados.

    Contexto de uso:
        Mantém a comparação consistente entre registros internos e produtos do
        site, reduzindo o risco de duplicar um item com identidade equivalente.
    """

    brand_aliases = _build_brand_aliases(product.brand)
    normalized_name = normalize_text(product.name)
    name_without_brand = _strip_brand_aliases(normalized_name, brand_aliases)
    name_without_variant = re.sub(r"\b\d+[\.,]?\d*\s*(ml|g|kg|l)\b", " ", name_without_brand)
    normalized_name_core = re.sub(r"\s+", " ", name_without_variant).strip()
    normalized_name_core = " ".join(
        token
        for token in normalized_name_core.split()
        if token not in GENERIC_NAME_TOKENS
    ).strip()

    return {
        "brand": normalize_text(product.brand),
        "name_core": normalized_name_core,
        "product_type": _normalize_product_type(product.concentration or product.name),
        "variant": normalize_variant(product.variant),
    }


def _build_brand_aliases(raw_brand: str) -> List[str]:
    """
    Responsabilidade:
        Derivar aliases simples de marca para remover ruído do nome-base.

    Parâmetros:
        raw_brand: Marca original do produto.

    Retorno:
        Lista de aliases normalizados, incluindo siglas quando fizer sentido.

    Contexto de uso:
        Ajuda a tratar casos como `CK Her`, em que a marca aparece abreviada no
        nome do perfume, enquanto o site pode usar a forma completa.
    """

    normalized_brand = normalize_text(raw_brand)
    if not normalized_brand:
        return []

    aliases = {normalized_brand}
    brand_parts = [part for part in normalized_brand.split() if part]
    if len(brand_parts) >= 2:
        initials = "".join(part[0] for part in brand_parts)
        if len(initials) >= 2:
            aliases.add(initials)

    return sorted(aliases, key=len, reverse=True)


def _strip_brand_aliases(raw_text: str, brand_aliases: List[str]) -> str:
    """
    Responsabilidade:
        Remover aliases de marca do texto para isolar o nome-base do perfume.

    Parâmetros:
        raw_text: Texto normalizado potencialmente contendo a marca.
        brand_aliases: Aliases derivados da marca do produto.

    Retorno:
        Texto sem a marca, com espaços normalizados.

    Contexto de uso:
        Evita que a marca atrapalhe a comparação do nome-base, especialmente em
        perfis abreviados como `CK One` versus `Calvin Klein One`.
    """

    cleaned_text = raw_text
    for alias in brand_aliases:
        if not alias:
            continue
        cleaned_text = re.sub(rf"\b{re.escape(alias)}\b", " ", cleaned_text)

    return re.sub(r"\s+", " ", cleaned_text).strip()


def _normalize_product_type(raw_text: str) -> str:
    """
    Responsabilidade:
        Normalizar concentração/tipo do perfume para comparação segura.

    Parâmetros:
        raw_text: Texto vindo da concentração ou do nome do produto.

    Retorno:
        Tipo consolidado, como `edt`, `edp` ou string vazia.

    Contexto de uso:
        Mantém EDT, EDP e variações textuais equivalentes alinhadas sem fundir
        famílias diferentes como `EDT` e `EDP`.
    """

    normalized_text = normalize_text(raw_text)
    if not normalized_text:
        return ""

    if "eau de parfum" in normalized_text or re.search(r"\bedp\b", normalized_text):
        return "edp"
    if "eau de toilette" in normalized_text or re.search(r"\bedt\b", normalized_text):
        return "edt"
    if "elixir" in normalized_text:
        return "elixir"
    if "parfum" in normalized_text:
        return "parfum"

    return ""


def _calculate_token_similarity(left_text: str, right_text: str) -> float:
    """
    Responsabilidade:
        Medir similaridade simples entre nomes-base usando sobreposição de tokens.

    Parâmetros:
        left_text: Nome-base do primeiro produto já normalizado.
        right_text: Nome-base do segundo produto já normalizado.

    Retorno:
        Score entre 0 e 1 baseado na interseção dos tokens informativos.

    Contexto de uso:
        Ajuda a marcar candidatos médios sem auto-linkar itens que só parecem
        parecidos superficialmente à primeira vista.
    """

    left_tokens = {token for token in left_text.split() if len(token) >= 2}
    right_tokens = {token for token in right_text.split() if len(token) >= 2}
    if not left_tokens or not right_tokens:
        return 0.0

    union_size = len(left_tokens | right_tokens)
    if union_size == 0:
        return 0.0

    return len(left_tokens & right_tokens) / union_size


def _has_hard_conflict(site_identity: dict[str, str], existing_identity: dict[str, str]) -> bool:
    """
    Responsabilidade:
        Detectar divergências fortes que bloqueiam vínculo automático.

    Parâmetros:
        site_identity: Sinais estáveis extraídos do produto do site.
        existing_identity: Sinais estáveis extraídos do produto interno.

    Retorno:
        True quando houver conflito forte; False caso contrário.

    Contexto de uso:
        Implementa a regra de segurança que impede unir perfumes claramente
        diferentes, como EDT versus EDP ou variantes de volume divergentes.
    """

    if (
        site_identity["product_type"]
        and existing_identity["product_type"]
        and site_identity["product_type"] != existing_identity["product_type"]
    ):
        return True

    if (
        site_identity["variant"]
        and existing_identity["variant"]
        and site_identity["variant"] != existing_identity["variant"]
    ):
        return True

    return False


def _build_match_timestamp() -> str:
    """
    Responsabilidade:
        Gerar timestamp ISO estável para auditoria de reconciliação.

    Parâmetros:
        Nenhum.

    Retorno:
        Texto ISO8601 em UTC com o instante atual.

    Contexto de uso:
        Registra quando um item foi vinculado ou recebeu candidato, facilitando
        observabilidade e futuras telas de revisão manual.
    """

    return datetime.now(timezone.utc).isoformat()
