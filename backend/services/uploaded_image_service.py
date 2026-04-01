"""
Serviço de persistência e resolução de imagens manuais do catálogo.

Este módulo separa o armazenamento de uploads do diretório de assets estáticos
versionados, permitindo que fotos enviadas pelo operador sobrevivam a refresh,
restart e novos deploys quando o app usa volume persistente.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import UploadFile

from backend.services.matcher import normalize_text
from backend.services.storage_path_service import resolve_default_data_file


class UploadedImageService:
    """
    Responsabilidade:
        Persistir uploads de imagem e construir URLs públicas seguras.

    Parâmetros:
        storage_directory: Diretório persistente onde as imagens serão gravadas.

    Retorno:
        Serviço pronto para salvar e localizar imagens do catálogo manual.

    Contexto de uso:
        Reutilizado pelas rotas web de cadastro e edição para anexar fotos
        tiradas no celular ou escolhidas da galeria sem quebrar o deploy.
    """

    def __init__(self, storage_directory: Path) -> None:
        """
        Responsabilidade:
            Inicializar o diretório persistente das imagens manuais.

        Parâmetros:
            storage_directory: Pasta real usada para os uploads da aplicação.

        Retorno:
            Nenhum.

        Contexto de uso:
            Construído uma vez por processo e mantido em `app.state`.
        """

        self.storage_directory = storage_directory
        self.storage_directory.mkdir(parents=True, exist_ok=True)

    def save_uploaded_file(
        self,
        uploaded_file: UploadFile,
        *,
        product_alias: str,
        variant_label: str = "",
    ) -> str:
        """
        Responsabilidade:
            Salvar um upload de imagem em nome estável e previsível.

        Parâmetros:
            uploaded_file: Arquivo enviado pelo formulário multipart.
            product_alias: Alias do produto usado para compor o nome base.
            variant_label: Rótulo da variante quando a imagem for específica.

        Retorno:
            URL pública do arquivo salvo para uso imediato na interface.

        Contexto de uso:
            Chamado pelo fluxo manual para persistir fotos do catálogo interno
            sem depender do site de origem ou de assets versionados.
        """

        original_filename = str(uploaded_file.filename or "").strip()
        file_extension = self._resolve_safe_extension(original_filename)
        normalized_alias = self._build_safe_slug(product_alias, fallback_value="produto")
        normalized_variant = self._build_safe_slug(variant_label, fallback_value="")
        random_suffix = secrets.token_hex(6)

        filename_parts = [normalized_alias]
        if normalized_variant:
            filename_parts.append(normalized_variant)
        filename_parts.append(random_suffix)
        resolved_filename = "-".join(filename_parts) + file_extension

        target_file = self.storage_directory / resolved_filename
        file_content = uploaded_file.file.read()
        if not file_content:
            raise ValueError("A imagem enviada está vazia.")

        target_file.write_bytes(file_content)
        return self.build_public_url(resolved_filename)

    def build_public_url(self, filename: str) -> str:
        """
        Responsabilidade:
            Converter um nome de arquivo persistido em URL pública do dashboard.

        Parâmetros:
            filename: Nome já salvo no diretório de uploads persistentes.

        Retorno:
            URL pública consumível por templates e componentes da interface.

        Contexto de uso:
            Mantém o contrato entre storage físico e renderização da imagem
            desacoplado da estrutura interna de pastas do servidor.
        """

        normalized_filename = os.path.basename(str(filename or "").strip())
        if not normalized_filename:
            return ""
        return f"/dashboard/uploads/{normalized_filename}"

    def resolve_public_path(self, filename: str) -> Path | None:
        """
        Responsabilidade:
            Resolver o caminho absoluto de um upload público solicitado.

        Parâmetros:
            filename: Nome do arquivo recebido na rota pública.

        Retorno:
            Path absoluto do arquivo quando ele existir; caso contrário, None.

        Contexto de uso:
            Permite servir imagens persistidas de forma segura, sem expor acesso
            arbitrário ao filesystem através da URL.
        """

        normalized_filename = os.path.basename(str(filename or "").strip())
        if not normalized_filename:
            return None

        resolved_path = (self.storage_directory / normalized_filename).resolve()
        try:
            resolved_path.relative_to(self.storage_directory.resolve())
        except ValueError:
            return None

        if not resolved_path.is_file():
            return None
        return resolved_path

    def _resolve_safe_extension(self, original_filename: str) -> str:
        """
        Responsabilidade:
            Restringir a extensão do upload a formatos suportados pelo app.

        Parâmetros:
            original_filename: Nome original enviado pelo cliente.

        Retorno:
            Extensão segura normalizada, sempre começando com ponto.

        Contexto de uso:
            Reduz risco de persistir tipos inesperados e mantém as imagens
            alinhadas com os formatos realmente suportados pelos navegadores.
        """

        normalized_extension = Path(original_filename).suffix.lower()
        allowed_extensions = {".png", ".jpg", ".jpeg", ".webp"}
        if normalized_extension in allowed_extensions:
            return ".jpg" if normalized_extension == ".jpeg" else normalized_extension
        return ".png"

    def _build_safe_slug(self, raw_value: str, fallback_value: str) -> str:
        """
        Responsabilidade:
            Transformar texto livre em um slug curto para nome de arquivo.

        Parâmetros:
            raw_value: Texto bruto vindo do produto ou da variante.
            fallback_value: Valor usado quando o texto não gerar slug válido.

        Retorno:
            Trecho seguro e estável para compor o nome do arquivo.

        Contexto de uso:
            Evita caracteres problemáticos em nomes de upload e melhora a
            rastreabilidade dos arquivos sem depender de nomes originais.
        """

        normalized_value = normalize_text(raw_value).replace(" ", "-").strip("-")
        return normalized_value or fallback_value


def resolve_uploaded_images_directory() -> Path:
    """
    Responsabilidade:
        Definir o diretório persistente padrão para uploads de imagem.

    Parâmetros:
        Nenhum.

    Retorno:
        Path absoluto apontando para a pasta de uploads da aplicação.

    Contexto de uso:
        Permite override por variável de ambiente em produção e, na ausência
        dela, ancora os uploads dentro do diretório `data` do projeto.
    """

    configured_directory = os.getenv("PRODUCT_IMAGE_UPLOAD_DIR", "").strip()
    if configured_directory:
        return Path(configured_directory)

    return resolve_default_data_file("uploads")
