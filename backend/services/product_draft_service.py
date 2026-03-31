"""
Servico para gerar rascunhos de cadastro de produto a partir de uma URL.

Este modulo reaproveita fetcher e parser ja existentes para evitar duplicacao
de heuristicas entre dashboard web, API futura e fluxos manuais.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from backend.services.matcher import normalize_text, normalize_variant
from backend.services.product_store_service import ProductStoreService
from backend.utils.fetcher import FetchResult, Fetcher
from backend.utils.parser import PageData, parse_page_data


@dataclass(slots=True)
class ProductDraft:
    """
    Responsabilidade:
        Representar um rascunho de produto pronto para preencher o formulario.

    Parametros:
        alias: Identificador sugerido para persistencia no storage.
        brand: Marca inferida da pagina.
        name: Nome base inferido e limpo para cadastro.
        variant: Variante inferida quando encontrada.
        last_known_url: URL final observada apos redirects.
        last_known_sku: SKU sugerido pela pagina, ou "unknown" como fallback.
        source_title: Titulo bruto usado como apoio visual no formulario.
        image_url: Imagem principal inferida para preview opcional.

    Retorno:
        Estrutura tipada com os campos sugeridos para criacao do produto.

    Contexto de uso:
        Utilizada pela camada web para pre-preencher cadastro manual por URL.
    """

    alias: str
    brand: str
    name: str
    variant: str
    last_known_url: str
    last_known_sku: str
    source_title: str
    image_url: Optional[str]


@dataclass(slots=True)
class ProductDraftBuildResult:
    """
    Responsabilidade:
        Encapsular sucesso ou falha da inferencia de cadastro por URL.

    Parametros:
        success: Indica se houve material suficiente para montar um rascunho.
        draft: Rascunho inferido quando a operacao foi bem-sucedida.
        page_data: Dados crus extraidos da pagina para diagnostico e preview.
        message: Mensagem descritiva para UI e logs de operacao.
        error_code: Codigo semantico da falha quando o rascunho nao puder ser gerado.

    Retorno:
        Resultado padronizado para consumo pelas rotas do dashboard.

    Contexto de uso:
        Evita propagar excecoes cruas para a interface durante o auto-preenchimento.
    """

    success: bool
    draft: Optional[ProductDraft]
    page_data: Optional[PageData]
    message: str
    error_code: Optional[str]


class ProductDraftService:
    """
    Responsabilidade:
        Gerar rascunho de produto a partir de uma URL remota.

    Parametros:
        fetcher: Cliente HTTP reutilizavel para baixar a pagina alvo.
        product_store: Storage usado para evitar colisao de alias sugerido.

    Retorno:
        Instancia de servico pronta para uso pela camada web.

    Contexto de uso:
        Centraliza heuristicas de inferencia para manter o dashboard enxuto.
    """

    def __init__(self, fetcher: Fetcher, product_store: ProductStoreService) -> None:
        """
        Responsabilidade:
            Guardar dependencias necessarias para inferencia do cadastro.

        Parametros:
            fetcher: Cliente HTTP para download do HTML remoto.
            product_store: Servico de armazenamento consultado para alias unicos.

        Retorno:
            Nenhum.

        Contexto de uso:
            Inicializado sob demanda pela camada web usando servicos do app state.
        """

        self.fetcher = fetcher
        self.product_store = product_store

    def build_from_url(self, product_url: str) -> ProductDraftBuildResult:
        """
        Responsabilidade:
            Baixar a pagina e transformar seus sinais em um rascunho de produto.

        Parametros:
            product_url: URL inicial enviada pelo usuario para auto-preenchimento.

        Retorno:
            ProductDraftBuildResult com rascunho sugerido ou erro explicavel.

        Contexto de uso:
            Chamado pela tela de cadastro quando o usuario informa apenas o link.
        """

        sanitized_url = str(product_url).strip()
        if not sanitized_url:
            return ProductDraftBuildResult(
                success=False,
                draft=None,
                page_data=None,
                message="Informe uma URL valida para gerar o cadastro automatico.",
                error_code="EMPTY_URL",
            )

        try:
            fetch_result: FetchResult = self.fetcher.fetch_page(sanitized_url)
        except Exception as error:
            return ProductDraftBuildResult(
                success=False,
                draft=None,
                page_data=None,
                message=f"Nao foi possivel acessar a URL informada: {error}",
                error_code="FETCH_FAILED",
            )

        page_data = parse_page_data(
            page_url=fetch_result.final_url,
            html_content=fetch_result.html_content,
            configured_fallback_sku=None,
        )

        inferred_brand = self._infer_brand(page_data)
        inferred_variant = self._infer_variant(page_data)
        inferred_name = self._infer_name(page_data, inferred_brand, inferred_variant)

        if not inferred_name:
            return ProductDraftBuildResult(
                success=False,
                draft=None,
                page_data=page_data,
                message="A pagina foi lida, mas nao houve sinal suficiente para inferir o nome do produto.",
                error_code="NAME_NOT_FOUND",
            )

        inferred_alias = self._build_unique_alias(
            brand=inferred_brand,
            name=inferred_name,
            variant=inferred_variant,
        )
        if not inferred_alias:
            return ProductDraftBuildResult(
                success=False,
                draft=None,
                page_data=page_data,
                message="Nao foi possivel montar um alias confiavel a partir da pagina.",
                error_code="ALIAS_NOT_FOUND",
            )

        draft = ProductDraft(
            alias=inferred_alias,
            brand=inferred_brand,
            name=inferred_name,
            variant=inferred_variant,
            last_known_url=page_data.url,
            last_known_sku=(page_data.sku or "unknown").strip() or "unknown",
            source_title=page_data.title or page_data.name or "",
            image_url=page_data.image_url,
        )

        return ProductDraftBuildResult(
            success=True,
            draft=draft,
            page_data=page_data,
            message="Rascunho do produto gerado automaticamente a partir da URL.",
            error_code=None,
        )

    def _infer_brand(self, page_data: PageData) -> str:
        """
        Responsabilidade:
            Escolher a melhor marca candidata disponivel na pagina.

        Parametros:
            page_data: Dados extraidos do HTML remoto.

        Retorno:
            Marca sugerida em formato de exibicao, ou string vazia.

        Contexto de uso:
            A marca entra tanto no formulario quanto na montagem do alias.
        """

        return str(page_data.brand or "").strip()

    def _infer_variant(self, page_data: PageData) -> str:
        """
        Responsabilidade:
            Padronizar a variante extraida antes de preencher o formulario.

        Parametros:
            page_data: Dados parseados da pagina.

        Retorno:
            Variante compacta em formato estavel, ou string vazia.

        Contexto de uso:
            Mantem coerencia entre a inferencia automatica e o matcher existente.
        """

        raw_variant = str(page_data.variant or "").strip()
        normalized_variant = normalize_variant(raw_variant)
        return normalized_variant or raw_variant

    def _infer_name(self, page_data: PageData, brand: str, variant: str) -> str:
        """
        Responsabilidade:
            Limpar o nome inferido removendo sufixos comerciais e duplicidades.

        Parametros:
            page_data: Dados extraidos do HTML remoto.
            brand: Marca inferida usada para remover repeticao no nome.
            variant: Variante inferida usada para separar identidade estavel.

        Retorno:
            Nome base sugerido para cadastro, ou string vazia se nada restar.

        Contexto de uso:
            Ajuda a aproximar o cadastro automatico do formato esperado pelo resolver.
        """

        best_candidate_name = ""
        best_candidate_score = -999
        best_candidate_token_count = 999

        for candidate_source, raw_candidate in self._list_name_candidates(page_data):
            cleaned_candidate_name = self._clean_name_candidate(
                raw_candidate=raw_candidate,
                brand=brand,
                variant=variant,
            )
            if not cleaned_candidate_name:
                continue

            candidate_score = self._score_name_candidate(
                candidate_source=candidate_source,
                raw_candidate=raw_candidate,
                cleaned_candidate_name=cleaned_candidate_name,
                brand=brand,
                variant=variant,
            )
            candidate_token_count = len(normalize_text(cleaned_candidate_name).split())

            # Decisao tecnica:
            # Em caso de empate, preferimos a versao mais curta porque ela tende
            # a representar melhor o nome operacional do produto do que frases
            # longas de vitrine ou SEO.
            if candidate_score > best_candidate_score or (
                candidate_score == best_candidate_score and candidate_token_count < best_candidate_token_count
            ):
                best_candidate_name = cleaned_candidate_name
                best_candidate_score = candidate_score
                best_candidate_token_count = candidate_token_count

        return best_candidate_name

    def _list_name_candidates(self, page_data: PageData) -> list[tuple[str, str]]:
        """
        Responsabilidade:
            Reunir candidatos textuais para o nome em ordem de confianca.

        Parametros:
            page_data: Dados extraidos da pagina remota.

        Retorno:
            Lista de pares com a origem do texto e o conteudo correspondente.

        Contexto de uso:
            Permite avaliar descricao, nome e titulo sem acoplar a decisao a um
            unico campo, o que reduz erros em paginas com SEO muito agressivo.
        """

        candidates: list[tuple[str, str]] = []
        for candidate_source, raw_candidate in (
            ("description", str(page_data.description or "").strip()),
            ("name", str(page_data.name or "").strip()),
            ("title", str(page_data.title or "").strip()),
        ):
            if raw_candidate:
                candidates.append((candidate_source, raw_candidate))

        return candidates

    def _clean_name_candidate(self, raw_candidate: str, brand: str, variant: str) -> str:
        """
        Responsabilidade:
            Limpar um candidato textual ate ele se aproximar do nome real.

        Parametros:
            raw_candidate: Texto bruto vindo de descricao, nome ou titulo.
            brand: Marca inferida usada para remover repeticao desnecessaria.
            variant: Variante inferida removida do nome base quando aparecer.

        Retorno:
            Nome limpo e adequado para cadastro, ou string vazia.

        Contexto de uso:
            Centraliza a higienizacao do nome para que todas as fontes textuais
            passem pela mesma regra antes de competir entre si.
        """

        candidate_without_store_suffix = self._strip_store_suffix(raw_candidate)
        candidate_without_marketing = self._strip_marketing_fragments(candidate_without_store_suffix)
        candidate_without_descriptors = self._strip_descriptor_suffixes(candidate_without_marketing)
        without_brand = self._remove_case_insensitive_fragment(candidate_without_descriptors, brand)
        without_variant = self._remove_case_insensitive_fragment(without_brand, variant)
        without_fillers = self._strip_edge_fillers(without_variant)
        cleaned_name = re.sub(r"\s+", " ", without_fillers).strip(" -|,:;")

        # Decisao tecnica:
        # Quando a limpeza fica agressiva demais, caimos para a versao sem
        # remocao de marca/variante para preservar algum sinal util.
        if cleaned_name:
            return cleaned_name

        fallback_name = re.sub(r"\s+", " ", candidate_without_descriptors).strip(" -|,:;")
        return fallback_name

    def _score_name_candidate(
        self,
        candidate_source: str,
        raw_candidate: str,
        cleaned_candidate_name: str,
        brand: str,
        variant: str,
    ) -> int:
        """
        Responsabilidade:
            Atribuir prioridade ao melhor nome operacional entre varios textos.

        Parametros:
            candidate_source: Origem do texto avaliado, como description ou title.
            raw_candidate: Texto bruto original antes da limpeza.
            cleaned_candidate_name: Nome final obtido apos higienizacao.
            brand: Marca inferida usada para avaliar consistencia do sinal.
            variant: Variante inferida usada para reforcar relevancia textual.

        Retorno:
            Pontuacao inteira; quanto maior, melhor o candidato.

        Contexto de uso:
            Mantem a escolha do nome explicavel e simples, sem depender de
            heuristicas opacas ou pesos excessivamente sofisticados.
        """

        source_weights = {"description": 6, "name": 5, "title": 4}
        normalized_raw_candidate = normalize_text(raw_candidate)
        normalized_cleaned_candidate = normalize_text(cleaned_candidate_name)
        normalized_brand = normalize_text(brand)
        normalized_variant = normalize_variant(variant)
        cleaned_token_count = len(normalized_cleaned_candidate.split())

        score = source_weights.get(candidate_source, 0)
        if self._looks_like_product_description(raw_candidate):
            score += 2
        if self._looks_like_marketing_heavy_text(raw_candidate):
            score -= 5
        if normalized_brand and normalized_brand in normalized_raw_candidate:
            score += 1
        if normalized_variant and normalized_variant in normalize_variant(raw_candidate):
            score += 1

        if cleaned_token_count == 0:
            return -999
        if cleaned_token_count <= 5:
            score += 2
        elif cleaned_token_count <= 7:
            score += 1
        else:
            score -= cleaned_token_count - 7

        return score

    def _select_name_candidate(self, page_data: PageData) -> str:
        """
        Responsabilidade:
            Escolher a melhor fonte textual para o nome do produto no cadastro.

        Parametros:
            page_data: Dados extraidos da pagina remota.

        Retorno:
            Texto candidato mais descritivo disponivel, ou string vazia.

        Contexto de uso:
            Prioriza descricao de produto quando ela parece mais informativa do
            que um titulo de marketing de vitrine.
        """

        descriptive_candidate = str(page_data.description or "").strip()
        if descriptive_candidate and self._looks_like_product_description(descriptive_candidate):
            return descriptive_candidate

        fallback_candidate = str(page_data.name or page_data.title or "").strip()
        if fallback_candidate:
            return fallback_candidate

        return descriptive_candidate

    def _strip_store_suffix(self, raw_title: str) -> str:
        """
        Responsabilidade:
            Remover sufixos comuns de titulo de e-commerce e nome da loja.

        Parametros:
            raw_title: Texto bruto vindo de title ou og:title.

        Retorno:
            Primeiro bloco relevante do titulo quando houver sufixo comercial.

        Contexto de uso:
            Evita que o nome do varejista ou mensagens promocionais entrem no cadastro.
        """

        sanitized_title = str(raw_title).strip()
        if not sanitized_title:
            return ""

        separators = [" | ", " - "]
        store_keywords = ("renner", "lojas renner", "compre online", "site oficial")

        for separator in separators:
            parts = [part.strip() for part in sanitized_title.split(separator) if part.strip()]
            if len(parts) < 2:
                continue

            last_part_normalized = normalize_text(parts[-1])
            if any(keyword in last_part_normalized for keyword in store_keywords):
                return parts[0]

        return sanitized_title

    def _strip_marketing_fragments(self, raw_text: str) -> str:
        """
        Responsabilidade:
            Remover chamadas promocionais comuns antes de montar o nome final.

        Parametros:
            raw_text: Texto candidato a nome vindo da pagina.

        Retorno:
            Texto mais proximo da descricao do produto, sem slogans comuns.

        Contexto de uso:
            Evita que campanhas comerciais e verbos promocionais virem nome de
            cadastro durante o auto-preenchimento.
        """

        sanitized_text = str(raw_text).strip()
        if not sanitized_text:
            return ""

        promotional_patterns = [
            r"\bcompre\s+online\b.*",
            r"\baproveite\b.*",
            r"\bconfira\b.*",
            r"\bsite\s+oficial\b.*",
            r"\bfrete\s+gratis\b.*",
            r"\bdesconto\b.*",
            r"\boferta\b.*",
        ]

        cleaned_text = sanitized_text
        for promotional_pattern in promotional_patterns:
            cleaned_text = re.sub(promotional_pattern, " ", cleaned_text, flags=re.IGNORECASE)

        return re.sub(r"\s+", " ", cleaned_text).strip(" -|,:;")

    def _looks_like_marketing_heavy_text(self, raw_text: str) -> bool:
        """
        Responsabilidade:
            Detectar quando um texto parece dominado por discurso comercial.

        Parametros:
            raw_text: Texto candidato vindo de titulo, nome ou descricao.

        Retorno:
            True quando o texto parece mais promocional do que descritivo.

        Contexto de uso:
            Ajuda a rebaixar fontes de SEO agressivo sem descartar totalmente o
            sinal, preservando um fallback quando a pagina for muito pobre.
        """

        normalized_text = normalize_text(raw_text)
        if not normalized_text:
            return False

        marketing_keywords = (
            "compre online",
            "desconto",
            "oferta",
            "aproveite",
            "imperdivel",
            "promocao",
            "frete gratis",
            "site oficial",
            "lancamento",
            "exclusivo",
        )
        marketing_hits = sum(1 for keyword in marketing_keywords if keyword in normalized_text)
        return marketing_hits >= 2

    def _looks_like_product_description(self, raw_text: str) -> bool:
        """
        Responsabilidade:
            Decidir se uma descricao parece conter nome real do produto.

        Parametros:
            raw_text: Texto candidato vindo de metadescricao ou campo similar.

        Retorno:
            True quando o texto parece descritivo e util para cadastro.

        Contexto de uso:
            Filtra descricoes vazias ou totalmente promocionais antes de usalas
            como fonte primaria do campo `name`.
        """

        normalized_text = normalize_text(raw_text)
        if not normalized_text:
            return False

        marketing_keywords = (
            "compre online",
            "site oficial",
            "desconto",
            "oferta",
            "aproveite",
            "frete gratis",
        )
        marketing_hits = sum(1 for keyword in marketing_keywords if keyword in normalized_text)

        # Decisao tecnica:
        # Exigimos pelo menos duas palavras uteis e rejeitamos textos em que o
        # sinal promocional domina o conteudo, mantendo heuristica simples.
        useful_tokens = [token for token in normalized_text.split(" ") if token]
        return len(useful_tokens) >= 2 and marketing_hits < 2

    def _strip_descriptor_suffixes(self, raw_text: str) -> str:
        """
        Responsabilidade:
            Remover descritores genericos que nao pertencem ao nome do produto.

        Parametros:
            raw_text: Texto candidato ja sem os principais slogans comerciais.

        Retorno:
            Texto mais proximo do nome/descricao util do item.

        Contexto de uso:
            Evita que categoria, publico e concentracao virem parte do campo
            `name` quando o dado veio de metadescricao do e-commerce.
        """

        sanitized_text = str(raw_text).strip()
        if not sanitized_text:
            return ""

        descriptor_patterns = [
            r"\bperfume\s+(masculino|feminino|unissex)\b.*",
            r"\beau\s+de\s+(toilette|parfum|cologne)\b.*",
            r"\bdeo\s+colonia\b.*",
            r"\bcolonia\b.*",
            r"\bfragrancia\b.*",
        ]

        cleaned_text = sanitized_text
        for descriptor_pattern in descriptor_patterns:
            cleaned_text = re.sub(descriptor_pattern, " ", cleaned_text, flags=re.IGNORECASE)

        return re.sub(r"\s+", " ", cleaned_text).strip(" -|,:;")

    def _strip_edge_fillers(self, raw_text: str) -> str:
        """
        Responsabilidade:
            Remover palavras genericas das pontas sem mutilar o nome central.

        Parametros:
            raw_text: Texto ja limpo das principais campanhas e descritores.

        Retorno:
            Texto final sem conectores e termos operacionais irrelevantes nas bordas.

        Contexto de uso:
            Evita nomes como "Perfume Importado One Million Feminino" quando o
            miolo util seria apenas "One Million".
        """

        sanitized_text = str(raw_text).strip()
        if not sanitized_text:
            return ""

        leading_patterns = [
            r"^(perfume|perfumes|fragrancia|fragrancias|importado|importada|original)\b[\s:-]*",
        ]
        trailing_patterns = [
            r"[\s,-]+\b(masculino|feminino|unissex)\b$",
            r"[\s,-]+\b(de|do|da|para)\b$",
        ]

        cleaned_text = sanitized_text
        for leading_pattern in leading_patterns:
            cleaned_text = re.sub(leading_pattern, "", cleaned_text, flags=re.IGNORECASE)
        for trailing_pattern in trailing_patterns:
            cleaned_text = re.sub(trailing_pattern, "", cleaned_text, flags=re.IGNORECASE)

        return re.sub(r"\s+", " ", cleaned_text).strip(" -|,:;")

    def _remove_case_insensitive_fragment(self, raw_text: str, fragment: str) -> str:
        """
        Responsabilidade:
            Remover uma ocorrencia textual simples sem depender de regex complexa.

        Parametros:
            raw_text: Texto de origem que pode conter a marca ou variante.
            fragment: Trecho a ser removido quando encontrado.

        Retorno:
            Texto resultante apos tentativa de remocao.

        Contexto de uso:
            Heuristica leve para separar identidade do produto sem parser semantico pesado.
        """

        sanitized_text = str(raw_text).strip()
        sanitized_fragment = str(fragment).strip()
        if not sanitized_text or not sanitized_fragment:
            return sanitized_text

        pattern = re.compile(re.escape(sanitized_fragment), re.IGNORECASE)
        return pattern.sub(" ", sanitized_text, count=1)

    def _build_unique_alias(self, brand: str, name: str, variant: str) -> str:
        """
        Responsabilidade:
            Montar alias estavel e unico a partir dos campos inferidos.

        Parametros:
            brand: Marca sugerida para compor o alias.
            name: Nome sugerido para compor o alias.
            variant: Variante sugerida para diferenciar itens parecidos.

        Retorno:
            Alias em snake_case, com sufixo numerico quando ja existir.

        Contexto de uso:
            Garante que o usuario receba uma sugestao pronta para persistencia.
        """

        brand_tokens = self._build_alias_tokens(brand, max_tokens=2, use_variant_normalizer=False)
        name_tokens = self._build_alias_tokens(name, max_tokens=4, use_variant_normalizer=False)
        variant_tokens = self._build_alias_tokens(variant, max_tokens=1, use_variant_normalizer=True)
        alias_tokens = self._clamp_alias_tokens(brand_tokens, name_tokens, variant_tokens)

        if not alias_tokens:
            return ""

        base_alias = "_".join(alias_tokens)
        unique_alias = base_alias
        suffix_index = 2

        # Decisao tecnica:
        # Mantemos regra simples de sufixo incremental para evitar colisao sem
        # precisar alterar a estrutura atual do storage.
        while self.product_store.get_by_alias(unique_alias) is not None:
            unique_alias = f"{base_alias}_{suffix_index}"
            suffix_index += 1

        return unique_alias

    def _build_alias_tokens(self, raw_part: str, max_tokens: int, use_variant_normalizer: bool) -> list[str]:
        """
        Responsabilidade:
            Converter cada parte do alias em poucos tokens legiveis e estaveis.

        Parametros:
            raw_part: Texto original da marca, nome ou variante.
            max_tokens: Limite de tokens aproveitados dessa parte.
            use_variant_normalizer: Define se a parte deve usar a normalizacao de variante.

        Retorno:
            Lista de tokens enxutos prontos para compor o alias final.

        Contexto de uso:
            Reduz aliases gigantescos gerados por textos longos sem perder a
            identificacao principal do produto no cadastro.
        """

        normalized_part = normalize_variant(raw_part) if use_variant_normalizer else normalize_text(raw_part)
        if not normalized_part:
            return []

        tokens = [part for part in normalized_part.split(" ") if part]
        return tokens[:max_tokens]

    def _clamp_alias_tokens(
        self,
        brand_tokens: list[str],
        name_tokens: list[str],
        variant_tokens: list[str],
    ) -> list[str]:
        """
        Responsabilidade:
            Limitar o tamanho do alias sem perder as partes mais importantes.

        Parametros:
            brand_tokens: Tokens normalizados da marca.
            name_tokens: Tokens normalizados do nome principal.
            variant_tokens: Tokens normalizados da variante.

        Retorno:
            Lista final de tokens pronta para ser unida em snake_case.

        Contexto de uso:
            Mantem aliases curtos o bastante para manutencao manual, mas ainda
            reconheciveis para o time que opera o catalogo.
        """

        alias_tokens = [*brand_tokens, *name_tokens, *variant_tokens]
        while alias_tokens and len("_".join(alias_tokens)) > 48:
            if len(name_tokens) > 2:
                name_tokens.pop()
            elif len(brand_tokens) > 1:
                brand_tokens.pop()
            elif len(name_tokens) > 1:
                name_tokens.pop()
            else:
                alias_tokens = alias_tokens[:-1]
                continue

            alias_tokens = [*brand_tokens, *name_tokens, *variant_tokens]

        return alias_tokens
