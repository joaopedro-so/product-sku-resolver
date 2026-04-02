"""
Serviço de catálogo visual dos banners das prateleiras.

Este módulo concentra a relação entre a prateleira física, seus textos de
interface e o asset visual usado no topo dos cards e cabeçalhos relacionados.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True, slots=True)
class ShelfBannerVisual:
    """
    Responsabilidade:
        Representar a configuração visual completa de uma prateleira.

    Parâmetros:
        banner_key: Chave estável usada para CSS e rastreamento visual.
        banner_wordmark: Texto principal exibido sobre o banner.
        banner_sublabel: Texto secundário opcional exibido no banner.
        body_label: Rótulo curto exibido no corpo do card.
        legacy_title: Nome legado opcional mantido para compatibilidade visual.
        banner_image_file: Nome do arquivo de imagem atribuído à prateleira.

    Retorno:
        Estrutura imutável com os dados que alimentam a UI das prateleiras.

    Contexto de uso:
        Compartilhada entre a Home, o detalhe da prateleira e eventuais
        extensões futuras sem espalhar strings e caminhos em vários templates.
    """

    banner_key: str
    banner_wordmark: str
    banner_sublabel: str
    body_label: str
    legacy_title: str
    banner_image_file: str


class ShelfBannerService:
    """
    Responsabilidade:
        Centralizar a identidade visual das prateleiras e resolver seus assets.

    Parâmetros:
        static_directory: Diretório base de assets estáticos do frontend.

    Retorno:
        Serviço pronto para consultar metadados e URLs públicas dos banners.

    Contexto de uso:
        Evita duplicação entre rotas e mantém o catálogo visual das prateleiras
        como uma única fonte de verdade fácil de manter.
    """

    def __init__(self, static_directory: Path) -> None:
        """
        Responsabilidade:
            Guardar o diretório estático usado para validar os arquivos reais.

        Parâmetros:
            static_directory: Pasta `backend/web/static` do projeto.

        Retorno:
            Nenhum.

        Contexto de uso:
            Permite validar fallback localmente sem acoplar o serviço ao router.
        """

        self._static_directory = static_directory
        self._banner_directory = static_directory / "shelf-banners"
        self._resolved_public_urls: Dict[str, str] = {}

    def get_visual(self, shelf_number: int, shelf_title: str) -> ShelfBannerVisual:
        """
        Responsabilidade:
            Retornar a configuração visual oficial de uma prateleira.

        Parâmetros:
            shelf_number: Número físico da prateleira.
            shelf_title: Título operacional da prateleira.

        Retorno:
            ShelfBannerVisual com textos, chave visual e arquivo associado.

        Contexto de uso:
            Chamado pelas rotas para montar cards e headers de forma coerente.
        """

        visual_map: Dict[int, ShelfBannerVisual] = {
            1: ShelfBannerVisual(
                banner_key="arabes",
                banner_wordmark="PERFUMES ÁRABES",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-01-perfumes-arabes.png",
            ),
            2: ShelfBannerVisual(
                banner_key="azzaro",
                banner_wordmark="AZZARO",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-02-azzaro.png",
            ),
            3: ShelfBannerVisual(
                banner_key="calvin-klein",
                banner_wordmark="CALVIN KLEIN",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-03-calvin-klein.png",
            ),
            4: ShelfBannerVisual(
                banner_key="paco-rabanne",
                banner_wordmark="paco rabanne",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-04-paco-rabanne.png",
            ),
            5: ShelfBannerVisual(
                banner_key="carolina-herrera",
                banner_wordmark="CAROLINA HERRERA",
                banner_sublabel="FEMININO",
                body_label="Feminino",
                legacy_title="Carolina Herrera A",
                banner_image_file="shelf-05-carolina-herrera-feminino.png",
            ),
            6: ShelfBannerVisual(
                banner_key="carolina-herrera",
                banner_wordmark="CAROLINA HERRERA",
                banner_sublabel="MASCULINO",
                body_label="Masculino",
                legacy_title="Carolina Herrera B",
                banner_image_file="shelf-06-carolina-herrera-masculino.png",
            ),
            7: ShelfBannerVisual(
                banner_key="lancome",
                banner_wordmark="LANCÔME",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-07-lancome.png",
            ),
            8: ShelfBannerVisual(
                banner_key="giorgio-armani",
                banner_wordmark="GIORGIO ARMANI",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-08-giorgio-armani.png",
            ),
            9: ShelfBannerVisual(
                banner_key="ralph-lauren",
                banner_wordmark="RALPH LAUREN",
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="shelf-09-ralph-lauren.png",
            ),
        }

        return visual_map.get(
            shelf_number,
            ShelfBannerVisual(
                banner_key="default",
                banner_wordmark=shelf_title.upper(),
                banner_sublabel="",
                body_label="",
                legacy_title="",
                banner_image_file="",
            ),
        )

    def build_public_image_url(self, visual: ShelfBannerVisual) -> str:
        """
        Responsabilidade:
            Converter o arquivo do banner em URL pública apenas quando ele existir.

        Parâmetros:
            visual: Configuração visual da prateleira já resolvida.

        Retorno:
            URL pública do banner ou string vazia em caso de fallback.

        Contexto de uso:
            Protege a UI de estados de imagem quebrada e mantém o fallback
            elegante quando o asset ainda não estiver disponível.
        """

        normalized_file_name = visual.banner_image_file.strip()
        if not normalized_file_name:
            return ""

        cached_public_url = self._resolved_public_urls.get(normalized_file_name, "")
        if cached_public_url:
            return cached_public_url

        banner_path = self._banner_directory / normalized_file_name
        if not banner_path.is_file():
            return ""

        public_url = self._build_versioned_public_url(
            file_name=normalized_file_name,
            banner_path=banner_path,
        )
        self._resolved_public_urls[normalized_file_name] = public_url
        return public_url

    def _build_versioned_public_url(self, file_name: str, banner_path: Path) -> str:
        """
        Responsabilidade:
            Gerar uma URL publica estavel e versionada para o banner.

        Parametros:
            file_name: Nome do arquivo estatico configurado para a prateleira.
            banner_path: Caminho absoluto do arquivo real no disco.

        Retorno:
            URL publica com versao baseada no timestamp do arquivo.

        Contexto de uso:
            A versao no query param permanece identica entre renders e muda
            apenas quando a imagem e realmente trocada. Isso permite cache
            `immutable` no navegador sem prender o app para sempre a uma arte
            antiga quando o arquivo for atualizado.
        """

        version_token = str(int(banner_path.stat().st_mtime_ns))
        return f"/dashboard/static/shelf-banners/{file_name}?v={version_token}"
