"""
Testes unitários do serviço de persistência de imagens enviadas manualmente.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi import UploadFile

from backend.services.uploaded_image_service import UploadedImageService, resolve_uploaded_images_directory


def test_uploaded_image_service_salva_arquivo_e_gera_url_publica(tmp_path: Path) -> None:
    """
    Responsabilidade:
        Garantir persistência real da imagem manual fora do diretório estático.

    Parâmetros:
        tmp_path: Diretório temporário do pytest para isolamento do teste.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege o fluxo mobile de câmera/galeria, que precisa sobreviver a
        refresh e reinício do app no mesmo storage persistente.
    """

    image_service = UploadedImageService(storage_directory=tmp_path / "uploads")
    uploaded_file = UploadFile(
        filename="frasco.png",
        file=BytesIO(b"imagem-de-teste"),
    )

    public_url = image_service.save_uploaded_file(
        uploaded_file=uploaded_file,
        product_alias="perfume_interno",
        variant_label="100ml",
    )

    saved_files = list((tmp_path / "uploads").iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == b"imagem-de-teste"
    assert public_url.startswith("/dashboard/uploads/")
    assert image_service.resolve_public_path(saved_files[0].name) == saved_files[0]


def test_resolve_uploaded_images_directory_reaproveita_base_do_storage_configurado(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """
    Responsabilidade:
        Garantir que uploads manuais caiam no mesmo volume persistente do catalogo.

    Parametros:
        monkeypatch: Fixture usada para controlar variaveis de ambiente.
        tmp_path: Diretorio temporario que simula o volume persistente.

    Retorno:
        Nenhum.

    Contexto de uso:
        Protege o deploy na Railway, onde os JSONs ja apontam para um volume e
        as imagens precisam acompanhar essa mesma base de persistencia.
    """

    monkeypatch.delenv("PRODUCT_IMAGE_UPLOAD_DIR", raising=False)
    monkeypatch.setenv("PRODUCT_STORAGE_FILE", str(tmp_path / "persisted" / "products.json"))

    resolved_directory = resolve_uploaded_images_directory()

    assert resolved_directory == (tmp_path / "persisted" / "uploads")
