/*
  Decisao tecnica:
  Este arquivo adiciona apenas interacoes operacionais leves. A ideia e manter
  o dashboard funcional mesmo sem JavaScript, usando o script para copiar
  codigo da variante, compartilhar links e alternar variantes sem navegar.
*/

function applyVariantSelection(variantRoot, variantOption) {
  /*
    Responsabilidade:
      Aplicar no DOM os dados da variante escolhida pelo operador.

    Parametros:
      variantRoot: Container que concentra os elementos afetados pela troca.
      variantOption: Botao da variante que contem os dados em data attributes.

    Retorno:
      Nenhum.

    Contexto de uso:
      Reaproveitado em cards de prateleira e na tela de detalhe para trocar
      codigo da variante, barcode, links operacionais e imagem sem abrir
      outro produto.
  */

  if (!variantRoot || !variantOption) {
    return;
  }

  variantRoot.querySelectorAll("[data-variant-option]").forEach((element) => {
    element.classList.toggle("variant-chip--active", element === variantOption);
  });

  const selectedAlias = variantOption.dataset.variantAlias || "";
  const selectedLabel = variantOption.dataset.variantLabel || "";
  const selectedVariantCode = variantOption.dataset.variantCode || "";
  const selectedDetailHref = variantOption.dataset.variantDetailHref || "";
  const selectedBarcodeHref = variantOption.dataset.variantBarcodeHref || "";
  const selectedUpdateHref = variantOption.dataset.variantUpdateHref || "";
  const selectedEditHref = variantOption.dataset.variantEditHref || "";
  const selectedDeleteHref = variantOption.dataset.variantDeleteHref || "";
  const selectedSaveHref = variantOption.dataset.variantSaveHref || "";
  const selectedProductUrl = variantOption.dataset.variantProductUrl || "";
  const selectedImageUrl = variantOption.dataset.variantImageUrl || "";
  const selectedStatusLabel = variantOption.dataset.variantStatusValue || "";
  const selectedStatusTone = variantOption.dataset.variantStatusToneValue || "";
  const selectedTimestamp = variantOption.dataset.variantTimestampValue || "";
  const selectedBarcodeDataUri = variantOption.dataset.variantBarcodeDataUri || "";

  variantRoot.querySelectorAll("[data-variant-code-label]").forEach((element) => {
    element.textContent = selectedVariantCode;
    element.setAttribute("title", selectedVariantCode);
  });

  variantRoot.querySelectorAll("[data-variant-detail-link]").forEach((element) => {
    if (selectedDetailHref) {
      element.setAttribute("href", selectedDetailHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-barcode-link]").forEach((element) => {
    if (selectedBarcodeHref) {
      element.setAttribute("href", selectedBarcodeHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-update-form]").forEach((element) => {
    if (selectedUpdateHref) {
      element.setAttribute("action", selectedUpdateHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-edit-link]").forEach((element) => {
    if (selectedEditHref) {
      element.setAttribute("href", selectedEditHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-delete-form]").forEach((element) => {
    if (selectedDeleteHref) {
      element.setAttribute("action", selectedDeleteHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-save-form]").forEach((element) => {
    if (selectedSaveHref) {
      element.setAttribute("action", selectedSaveHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-product-link]").forEach((element) => {
    if (selectedProductUrl) {
      element.setAttribute("href", selectedProductUrl);
    }
  });

  variantRoot.querySelectorAll("[data-variant-label-display]").forEach((element) => {
    element.textContent = selectedLabel ? `• ${selectedLabel}` : "";
  });

  variantRoot.querySelectorAll("[data-variant-label-only]").forEach((element) => {
    element.textContent = selectedLabel || "Sem variante informada";
  });

  variantRoot.querySelectorAll("[data-variant-status-label]").forEach((element) => {
    element.textContent = selectedStatusLabel;
  });

  variantRoot.querySelectorAll("[data-variant-status-badge]").forEach((element) => {
    element.textContent = selectedStatusLabel;
    element.className = "status-badge";
    element.classList.add(`status-badge--${selectedStatusTone || "neutral"}`);
  });

  variantRoot.querySelectorAll("[data-variant-timestamp-label]").forEach((element) => {
    element.textContent = selectedTimestamp;
  });

  variantRoot.querySelectorAll("[data-variant-copy-trigger]").forEach((element) => {
    element.setAttribute("data-copy-text", selectedVariantCode);
  });

  const variantImage = variantRoot.querySelector("[data-variant-image]");
  if (variantImage && selectedImageUrl) {
    variantImage.setAttribute("src", selectedImageUrl);
  }

  const variantBarcodeImage = variantRoot.querySelector("[data-variant-barcode-image]");
  if (variantBarcodeImage && selectedBarcodeDataUri) {
    variantBarcodeImage.setAttribute("src", selectedBarcodeDataUri);
    variantBarcodeImage.setAttribute("alt", `Código de barras do código ${selectedVariantCode}`);
  }

  const storageKey = variantRoot.dataset.variantStorageKey || "";
  if (storageKey && selectedAlias) {
    window.localStorage.setItem(storageKey, selectedAlias);
  }
}

function initializeVariantSwitchers() {
  /*
    Responsabilidade:
      Restaurar a ultima variante escolhida e ativar os seletores da pagina.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Garante comportamento estavel entre navegacoes, seguindo a regra de usar
      a ultima variante escolhida quando o navegador ainda se lembra dela.
  */

  document.querySelectorAll("[data-variant-switcher]").forEach((variantRoot) => {
    const variantOptions = Array.from(variantRoot.querySelectorAll("[data-variant-option]"));
    if (!variantOptions.length) {
      return;
    }

    const storageKey = variantRoot.dataset.variantStorageKey || "";
    const rememberedAlias = storageKey ? window.localStorage.getItem(storageKey) || "" : "";
    const rememberedOption = rememberedAlias
      ? variantOptions.find((element) => element.dataset.variantAlias === rememberedAlias)
      : null;
    const activeOption = variantOptions.find((element) => element.classList.contains("variant-chip--active"));
    const initialOption = rememberedOption || activeOption || variantOptions[0];

    applyVariantSelection(variantRoot, initialOption);

    variantOptions.forEach((variantOption) => {
      variantOption.addEventListener("click", () => {
        applyVariantSelection(variantRoot, variantOption);
      });
    });
  });
}

function setFabMenuState(fabRoot, shouldOpen) {
  /*
    Responsabilidade:
      Sincronizar o estado visual e acessível do menu do FAB de criação.

    Parametros:
      fabRoot: Container raiz do FAB que concentra botão e atalhos rápidos.
      shouldOpen: Define se o menu deve ficar aberto ou fechado.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantém o comportamento do botão flutuante previsível no mobile sem
      depender de bibliotecas externas nem afetar o fluxo principal do app.
  */

  if (!fabRoot) {
    return;
  }

  const trigger = fabRoot.querySelector("[data-fab-trigger]");
  if (!trigger) {
    return;
  }

  fabRoot.dataset.open = shouldOpen ? "true" : "false";
  trigger.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function initializeCreateFab() {
  /*
    Responsabilidade:
      Ativar o botão flutuante de criação com menu rápido de atalhos.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Substitui o CTA grande do header por uma ação mais compacta e nativa
      para mobile, preservando o acesso aos fluxos de importar e cadastrar.
  */

  const fabRoot = document.querySelector("[data-fab-root]");
  const fabTrigger = fabRoot?.querySelector("[data-fab-trigger]");
  if (!fabRoot || !fabTrigger) {
    return;
  }

  setFabMenuState(fabRoot, false);

  fabTrigger.addEventListener("click", () => {
    const isOpen = fabRoot.dataset.open === "true";
    setFabMenuState(fabRoot, !isOpen);
  });

  document.addEventListener("click", (event) => {
    if (!fabRoot.contains(event.target)) {
      setFabMenuState(fabRoot, false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setFabMenuState(fabRoot, false);
    }
  });
}

document.addEventListener("click", async (event) => {
  const copyTrigger = event.target.closest("[data-copy-text]");
  if (copyTrigger) {
    event.preventDefault();
    const textToCopy = copyTrigger.getAttribute("data-copy-text") || "";
    if (!textToCopy) {
      return;
    }

    try {
      await navigator.clipboard.writeText(textToCopy);
      copyTrigger.textContent = "Copiado";
      window.setTimeout(() => {
        copyTrigger.textContent = copyTrigger.dataset.originalLabel || copyTrigger.textContent;
      }, 1200);
    } catch (error) {
      window.alert(`Não foi possível copiar o código: ${error}`);
    }
    return;
  }

  const shareTrigger = event.target.closest("[data-share-url]");
  if (shareTrigger) {
    event.preventDefault();
    const shareUrl = shareTrigger.getAttribute("data-share-url") || window.location.href;

    try {
      if (navigator.share) {
        await navigator.share({ url: shareUrl });
        return;
      }

      await navigator.clipboard.writeText(shareUrl);
      window.alert("Link copiado para a área de transferência.");
    } catch (error) {
      window.alert(`Não foi possível compartilhar: ${error}`);
    }
  }
});

/*
  Decisao tecnica:
  Guardamos o rotulo original dos botoes para que o feedback de "Copiado"
  volte ao estado anterior sem precisar duplicar logica na hora do clique.
*/
document.querySelectorAll("[data-copy-text]").forEach((element) => {
  if (!element.dataset.originalLabel) {
    element.dataset.originalLabel = element.textContent || "";
  }
});

initializeVariantSwitchers();
initializeCreateFab();
