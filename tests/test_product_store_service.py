"""
Testes do serviço de armazenamento de produtos.
"""

from pathlib import Path

from backend.models.product import ProductRecord
from backend.services.product_store_service import ProductStoreService


def test_upsert_and_get_by_alias(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar inserção e recuperação de produto por alias.

    Parâmetros:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante que a primeira camada de storage funciona antes da integração
        com API e resolver.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="one_million_200ml",
        brand="Paco Rabanne",
        name="One Million",
        variant="200ml",
        last_known_url="https://loja.exemplo/produto",
        last_known_sku="123",
    )

    store.upsert_product(product)
    found_product = store.get_by_alias("one_million_200ml")

    assert found_product is not None
    assert found_product.last_known_sku == "123"


def test_update_product_sku_and_url(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar atualização de SKU e URL mantendo identidade estável.

    Parâmetros:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Assegura regra de negócio de separar dados estáveis de mutáveis.
    """

    store = ProductStoreService(tmp_path / "products.json")
    original_product = ProductRecord(
        alias="example",
        brand="Marca",
        name="Produto",
        variant="Variante",
        last_known_url="https://antiga",
        last_known_sku="000",
    )
    store.upsert_product(original_product)

    updated_product = store.update_product_sku_and_url(
        product_alias="example",
        new_sku="999",
        new_url="https://nova",
    )

    assert updated_product.brand == "Marca"
    assert updated_product.name == "Produto"
    assert updated_product.variant == "Variante"
    assert updated_product.last_known_sku == "999"
    assert updated_product.last_known_url == "https://nova"


def test_upsert_deriva_page_family_sku_a_partir_da_url(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o storage preencha automaticamente o SKU estável da página.

    Parametros:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Retorno:
        Nenhum; valida derivação do identificador pai a partir da URL.

    Contexto de uso:
        Protege a separação entre o identificador estável da página do produto
        e o código operacional da variante usado no barcode.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="example",
        brand="Marca",
        name="Produto",
        variant="100ml",
        last_known_url="https://www.lojasrenner.com.br/p/produto/-/A-532004871-br.lr?sku=532004934",
        last_known_sku="532004934",
    )

    persisted_product = store.upsert_product(product)

    assert persisted_product.page_family_sku == "532004871"
    assert persisted_product.variant_code == "532004934"


def test_update_product_sku_and_url_preserva_prateleira_manual(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a atualizacao operacional de SKU nao remova a localizacao.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida preservacao da prateleira e da ordem manual.

    Contexto de uso:
        Evita regressao no fluxo de sincronizacao, onde apenas SKU e URL devem
        mudar enquanto a organizacao fisica continua sob controle manual.
    """

    store = ProductStoreService(tmp_path / "products.json")
    original_product = ProductRecord(
        alias="example",
        brand="Marca",
        name="Produto",
        variant="Variante",
        last_known_url="https://antiga",
        last_known_sku="000",
        shelf_number=7,
        display_order=4,
    )
    store.upsert_product(original_product)

    updated_product = store.update_product_sku_and_url(
        product_alias="example",
        new_sku="999",
        new_url="https://nova",
    )

    assert updated_product.shelf_number == 7
    assert updated_product.display_order == 4


def test_replace_product_permite_trocar_alias_sem_duplicar_registro(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar substituicao completa do produto quando o alias muda na edicao.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum.

    Contexto de uso:
        Garante que o fluxo de edicao web nao deixa o alias antigo persistido.
    """

    store = ProductStoreService(tmp_path / "products.json")
    original_product = ProductRecord(
        alias="produto_antigo",
        brand="Marca",
        name="Produto",
        variant="100ml",
        last_known_url="https://antiga",
        last_known_sku="001",
    )
    store.upsert_product(original_product)

    updated_product = ProductRecord(
        alias="produto_novo",
        brand="Marca atualizada",
        name="Produto atualizado",
        variant="150ml",
        last_known_url="https://nova",
        last_known_sku="002",
    )

    store.replace_product("produto_antigo", updated_product)

    assert store.get_by_alias("produto_antigo") is None
    found_product = store.get_by_alias("produto_novo")
    assert found_product is not None
    assert found_product.brand == "Marca atualizada"
    assert len(store.list_products()) == 1


def test_upsert_persiste_localizacao_manual_de_prateleira(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a localizacao manual de prateleira seja persistida no storage.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida leitura do produto com shelf_number e display_order.

    Contexto de uso:
        Protege o novo fluxo operacional de atribuicao manual de prateleira.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="produto_com_prateleira",
        brand="Paco Rabanne",
        name="Produto",
        variant="100ml",
        last_known_url="https://exemplo.com/produto",
        last_known_sku="123",
        shelf_number=4,
        display_order=2,
    )

    store.upsert_product(product)

    found_product = store.get_by_alias("produto_com_prateleira")
    assert found_product is not None
    assert found_product.shelf_number == 4
    assert found_product.display_order == 2


def test_delete_product_remove_registro_existente(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Validar a exclusao definitiva de um produto persistido no storage.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida remocao do alias e reducao da lista persistida.

    Contexto de uso:
        Protege a acao administrativa de exclusao usada pelo dashboard.
    """

    store = ProductStoreService(tmp_path / "products.json")
    product = ProductRecord(
        alias="produto_excluir",
        brand="Marca",
        name="Produto",
        variant="100ml",
        last_known_url="https://exemplo.com/produto",
        last_known_sku="321",
    )
    store.upsert_product(product)

    removed_product = store.delete_product("produto_excluir")

    assert removed_product.alias == "produto_excluir"
    assert store.get_by_alias("produto_excluir") is None
    assert store.list_products() == []


def test_upsert_persiste_produto_para_nova_instancia_do_storage(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que o cadastro sobreviva a nova leitura em outra sessao.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida persistencia real no arquivo e releitura posterior.

    Contexto de uso:
        Protege o fluxo do dashboard em cenarios de refresh, reabertura do app
        ou nova instancia do servico apontando para o mesmo arquivo.
    """

    storage_path = tmp_path / "products.json"
    first_store = ProductStoreService(storage_path)
    persisted_product = first_store.upsert_product(
        ProductRecord(
            alias="perfume_novo",
            brand="Marca",
            name="Perfume Novo",
            variant="100ml",
            last_known_url="https://exemplo.com/perfume-novo",
            last_known_sku="sku-100",
        )
    )

    second_store = ProductStoreService(storage_path)
    found_product = second_store.get_by_alias("perfume_novo")

    assert persisted_product.alias == "perfume_novo"
    assert found_product is not None
    assert found_product.name == "Perfume Novo"
    assert found_product.last_known_sku == "sku-100"


def test_upsert_reconcilia_produto_manual_com_retorno_do_site_sem_duplicar(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que um item manual volte a sincronizar sem virar duplicata.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida preservacao do alias interno e ausencia de registro extra.

    Contexto de uso:
        Protege o fluxo em que um perfume cadastrado manualmente reaparece no
        site e precisa retomar o sync mantendo identidade interna unica.
    """

    store = ProductStoreService(tmp_path / "products.json")
    manual_product = ProductRecord(
        alias="ck_one_interno_100ml",
        brand="Calvin Klein",
        name="CK One Eau de Toilette",
        variant="100ml",
        last_known_url="",
        last_known_sku="manual-100",
        source_type="manual",
        site_link_status="manual_unlinked",
        shelf_number=3,
        display_order=2,
    )
    store.upsert_product(manual_product)

    persisted_product = store.upsert_product(
        ProductRecord(
            alias="calvin_klein_ck_one_100ml",
            brand="Calvin Klein",
            name="Calvin Klein CK One Eau de Toilette",
            variant="100 ml",
            last_known_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=999",
            last_known_sku="999",
            source_type="site",
            page_family_sku="111",
        )
    )

    assert persisted_product.alias == "ck_one_interno_100ml"
    assert persisted_product.site_link_status == "linked_to_site"
    assert persisted_product.site_product_id == "111"
    assert persisted_product.last_known_sku == "999"
    assert persisted_product.variant_code == "999"
    assert persisted_product.shelf_number == 3
    assert persisted_product.display_order == 2
    assert store.get_by_alias("calvin_klein_ck_one_100ml") is None
    assert len(store.list_products()) == 1


def test_upsert_mantem_produto_manual_sem_link_quando_o_site_traz_item_ambiguo(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que itens ambiguos nao sejam unidos automaticamente.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida coexistencia segura entre manual e produto do site.

    Contexto de uso:
        Evita regressao em casos como EDT versus EDP dentro da mesma familia.
    """

    store = ProductStoreService(tmp_path / "products.json")
    store.upsert_product(
        ProductRecord(
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
    )

    persisted_site_product = store.upsert_product(
        ProductRecord(
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
    )

    assert persisted_site_product.alias == "the_icon_edp_site_100ml"
    assert store.get_by_alias("the_icon_edt_interno_100ml") is not None
    assert len(store.list_products()) == 2


def test_upsert_reconcilia_variantes_do_mesmo_produto_pai_por_volume(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que cada variante manual seja religada ao site corretamente.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida reconciliacao de multiplas variantes de um mesmo perfume.

    Contexto de uso:
        Protege o modelo pai + variantes quando um produto volta ao site com
        mais de um volume e cada codigo precisa ser atualizado separadamente.
    """

    store = ProductStoreService(tmp_path / "products.json")
    store.upsert_product(
        ProductRecord(
            alias="good_girl_interno_50ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="50ml",
            last_known_url="",
            last_known_sku="manual-50",
            source_type="manual",
            site_link_status="manual_unlinked",
            parent_reference="good_girl",
            shelf_number=5,
        )
    )
    store.upsert_product(
        ProductRecord(
            alias="good_girl_interno_80ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="80ml",
            last_known_url="",
            last_known_sku="manual-80",
            source_type="manual",
            site_link_status="manual_unlinked",
            parent_reference="good_girl",
            shelf_number=5,
        )
    )

    store.upsert_product(
        ProductRecord(
            alias="good_girl_site_50ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="50ml",
            last_known_url="https://www.lojasrenner.com.br/p/good-girl/-/A-500-br.lr?sku=550",
            last_known_sku="550",
            source_type="site",
            page_family_sku="500",
        )
    )
    store.upsert_product(
        ProductRecord(
            alias="good_girl_site_80ml",
            brand="Carolina Herrera",
            name="Good Girl",
            variant="80ml",
            last_known_url="https://www.lojasrenner.com.br/p/good-girl/-/A-500-br.lr?sku=880",
            last_known_sku="880",
            source_type="site",
            page_family_sku="500",
        )
    )

    persisted_variant_50ml = store.get_by_alias("good_girl_interno_50ml")
    persisted_variant_80ml = store.get_by_alias("good_girl_interno_80ml")

    assert persisted_variant_50ml is not None
    assert persisted_variant_80ml is not None
    assert persisted_variant_50ml.site_link_status == "linked_to_site"
    assert persisted_variant_80ml.site_link_status == "linked_to_site"
    assert persisted_variant_50ml.last_known_sku == "550"
    assert persisted_variant_80ml.last_known_sku == "880"
    assert persisted_variant_50ml.shelf_number == 5
    assert persisted_variant_80ml.shelf_number == 5
    assert len(store.list_products()) == 2


def test_upsert_atualiza_registro_ja_vinculado_sem_recriar_alias_do_site(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que futuras leituras do site atualizem o item ja reconciliado.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida ausencia de duplicata apos o primeiro vinculo.

    Contexto de uso:
        Protege o caso em que o mesmo perfume religado volta a ser importado ou
        atualizado novamente em ciclos seguintes de sincronizacao.
    """

    store = ProductStoreService(tmp_path / "products.json")
    store.upsert_product(
        ProductRecord(
            alias="ck_one_interno_100ml",
            brand="Calvin Klein",
            name="CK One Eau de Toilette",
            variant="100ml",
            last_known_url="",
            last_known_sku="manual-100",
            source_type="manual",
            site_link_status="manual_unlinked",
            shelf_number=3,
        )
    )
    store.upsert_product(
        ProductRecord(
            alias="calvin_klein_ck_one_100ml",
            brand="Calvin Klein",
            name="Calvin Klein CK One Eau de Toilette",
            variant="100ml",
            last_known_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=999",
            last_known_sku="999",
            source_type="site",
            page_family_sku="111",
        )
    )

    refreshed_product = store.upsert_product(
        ProductRecord(
            alias="site_alias_novo_ck_one_100ml",
            brand="Calvin Klein",
            name="Calvin Klein CK One Eau de Toilette",
            variant="100ml",
            last_known_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=1001",
            last_known_sku="1001",
            source_type="site",
            page_family_sku="111",
        )
    )

    assert refreshed_product.alias == "ck_one_interno_100ml"
    assert refreshed_product.last_known_sku == "1001"
    assert refreshed_product.current_site_code == "1001"
    assert refreshed_product.shelf_number == 3
    assert store.get_by_alias("site_alias_novo_ck_one_100ml") is None
    assert len(store.list_products()) == 1


def test_confirm_site_candidate_promove_item_manual_para_vinculado(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que a confirmacao manual retome o sync usando o candidato salvo.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida promocao do estado `candidate_found` para `linked_to_site`.

    Contexto de uso:
        Protege a acao manual do dashboard quando o operador reconhece a
        correspondencia sugerida pelo reconciliador.
    """

    store = ProductStoreService(tmp_path / "products.json")
    store.upsert_product(
        ProductRecord(
            alias="ck_one_interno_100ml",
            brand="Calvin Klein",
            name="CK One Eau de Toilette",
            variant="100ml",
            last_known_url="",
            last_known_sku="manual-100",
            source_type="manual",
            site_link_status="candidate_found",
            site_candidate_id="111",
            site_candidate_url="https://www.lojasrenner.com.br/p/ck-one/-/A-111-br.lr?sku=999",
            site_candidate_code="999",
            site_candidate_variant_id="variant-999",
            shelf_number=3,
        )
    )

    confirmed_product = store.confirm_site_candidate("ck_one_interno_100ml")

    assert confirmed_product.site_link_status == "linked_to_site"
    assert confirmed_product.site_product_id == "111"
    assert confirmed_product.last_known_sku == "999"
    assert confirmed_product.current_barcode_value == "999"
    assert confirmed_product.site_variant_id == "variant-999"
    assert confirmed_product.site_candidate_id == ""
    assert confirmed_product.shelf_number == 3


def test_ignore_site_candidate_limpa_alerta_sem_apagar_cadastro_manual(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir que ignorar o candidato devolva o item ao estado manual solto.

    Parametros:
        tmp_path: Diretorio temporario fornecido pelo pytest.

    Retorno:
        Nenhum; valida limpeza dos dados temporarios do candidato.

    Contexto de uso:
        Protege o fluxo em que a sugestao do site nao corresponde ao item real
        da loja e o operador decide manter apenas o cadastro interno.
    """

    store = ProductStoreService(tmp_path / "products.json")
    store.upsert_product(
        ProductRecord(
            alias="the_icon_interno_100ml",
            brand="Antonio Banderas",
            name="The Icon Eau de Toilette",
            variant="100ml",
            last_known_url="",
            last_known_sku="manual-100",
            source_type="manual",
            site_link_status="candidate_found",
            site_candidate_id="222",
            site_candidate_url="https://www.lojasrenner.com.br/p/the-icon/-/A-222-br.lr?sku=333",
            site_candidate_code="333",
        )
    )

    ignored_product = store.ignore_site_candidate("the_icon_interno_100ml")

    assert ignored_product.site_link_status == "manual_unlinked"
    assert ignored_product.site_candidate_id == ""
    assert ignored_product.site_candidate_url == ""
    assert ignored_product.site_candidate_code == ""
    assert ignored_product.last_known_sku == "manual-100"
