"""
Testes do servico de reconciliacao entre catalogo interno e retorno do site.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.product_reconciliation_service import ProductReconciliationService
from backend.services.site_link_override_service import SiteLinkOverrideService


def _build_service_with_empty_override_file(tmp_path: Path) -> ProductReconciliationService:
    """
    Responsabilidade:
        Criar o reconciliador apontando para um arquivo vazio e isolado.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        ProductReconciliationService configurado para o teste atual.

    Contexto de uso:
        Mantem os testes deterministas sem depender do arquivo versionado do
        projeto nem de configuracoes externas do ambiente.
    """

    override_file = tmp_path / "manual_site_link_overrides.json"
    override_file.write_text('{"overrides": []}', encoding="utf-8")
    return ProductReconciliationService(
        override_service=SiteLinkOverrideService(storage_file_path=override_file)
    )


def test_reconciliador_auto_linka_produto_manual_com_mesma_identidade(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir auto-link quando marca, nome, tipo e variante coincidirem.

    Parametros:
        tmp_path: Diretorio temporario usado para isolar o arquivo de overrides.

    Retorno:
        Nenhum; valida decisao segura de `linked_to_site`.

    Contexto de uso:
        Protege o caso central de um item manual que volta ao site depois e
        deve retomar sincronizacao sem criar duplicata.
    """

    reconciliation_service = _build_service_with_empty_override_file(tmp_path)
    manual_product = ProductRecord(
        alias="ck_one_interno_100ml",
        brand="Calvin Klein",
        name="CK One Eau de Toilette",
        variant="100ml",
        last_known_url="",
        last_known_sku="manual-100",
        source_type="manual",
        site_link_status="manual_unlinked",
    )
    site_product = ProductRecord(
        alias="calvin_klein_ck_one_100ml",
        brand="Calvin Klein",
        name="Calvin Klein CK One Eau de Toilette",
        variant="100 ml",
        last_known_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=999",
        last_known_sku="999",
        source_type="site",
        page_family_sku="111",
    )

    decision = reconciliation_service.decide_site_link(site_product, [manual_product])

    assert decision.decision_type == "linked_to_site"
    assert decision.target_alias == "ck_one_interno_100ml"
    assert decision.site_product_id == "111"
    assert decision.confidence is not None
    assert decision.confidence >= 0.92


def test_reconciliador_nao_mescla_produtos_com_concentracao_diferente(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que EDT e EDP semelhantes nao sejam auto-linkados por engano.

    Parametros:
        tmp_path: Diretorio temporario usado para isolar o arquivo de overrides.

    Retorno:
        Nenhum; valida ausencia de vinculo automatico em caso ambiguo.

    Contexto de uso:
        Evita regressao em familias como The Icon, onde o nome-base se repete
        mas a concentracao define produtos realmente diferentes.
    """

    reconciliation_service = _build_service_with_empty_override_file(tmp_path)
    manual_product = ProductRecord(
        alias="the_icon_edt_interno_100ml",
        brand="Antonio Banderas",
        name="The Icon Eau de Toilette",
        variant="100ml",
        last_known_url="",
        last_known_sku="manual-100",
        source_type="manual",
        concentration="EDT",
        site_link_status="manual_unlinked",
    )
    site_product = ProductRecord(
        alias="the_icon_edp_site_100ml",
        brand="Antonio Banderas",
        name="The Icon Eau de Parfum",
        variant="100ml",
        last_known_url="https://www.lojasrenner.com.br/p/the-icon-edp/-/A-222-br.lr?sku=333",
        last_known_sku="333",
        source_type="site",
        concentration="EDP",
        page_family_sku="222",
    )

    decision = reconciliation_service.decide_site_link(site_product, [manual_product])

    assert decision.decision_type == "none"
    assert decision.target_alias == ""


def test_reconciliador_respeita_override_manual_antes_da_heuristica(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o override manual tenha prioridade maxima no vinculo.

    Parametros:
        tmp_path: Diretorio temporario usado para montar o arquivo de override.

    Retorno:
        Nenhum; valida uso do alias curado manualmente.

    Contexto de uso:
        Protege casos em que a operacao conhece a correspondencia correta e nao
        quer depender do score heuristico para religar um item ao site.
    """

    override_file = tmp_path / "manual_site_link_overrides.json"
    override_file.write_text(
        """
        {
          "overrides": [
            {
              "internal_alias": "the_icon_edt_interno_100ml",
              "site_product_id": "222",
              "site_variant_label": "100ml"
            }
          ]
        }
        """.strip(),
        encoding="utf-8",
    )
    reconciliation_service = ProductReconciliationService(
        override_service=SiteLinkOverrideService(storage_file_path=override_file)
    )
    manual_product = ProductRecord(
        alias="the_icon_edt_interno_100ml",
        brand="Antonio Banderas",
        name="The Icon Eau de Toilette",
        variant="100ml",
        last_known_url="",
        last_known_sku="manual-100",
        source_type="manual",
        site_link_status="manual_unlinked",
    )
    site_product = ProductRecord(
        alias="the_icon_edt_site_100ml",
        brand="Antonio Banderas",
        name="The Icon Eau de Toilette",
        variant="100ml",
        last_known_url="https://www.lojasrenner.com.br/p/the-icon-edt/-/A-222-br.lr?sku=333",
        last_known_sku="333",
        source_type="site",
        page_family_sku="222",
    )

    decision = reconciliation_service.decide_site_link(site_product, [manual_product])

    assert decision.decision_type == "linked_to_site"
    assert decision.target_alias == "the_icon_edt_interno_100ml"
    assert decision.confidence == 1.0
