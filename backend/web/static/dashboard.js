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
  const selectedIsSaved = variantOption.dataset.variantIsSaved === "1";
  const selectedSaveLabel = variantOption.dataset.variantSaveLabel || (selectedIsSaved ? "Remover dos salvos" : "Salvar");
  const selectedProductUrl = variantOption.dataset.variantProductUrl || "";
  const selectedImageUrl = variantOption.dataset.variantImageUrl || "";
  const selectedStatusLabel = variantOption.dataset.variantStatusValue || "";
  const selectedStatusTone = variantOption.dataset.variantStatusToneValue || "";
  const selectedTimestamp = variantOption.dataset.variantTimestampValue || "";
  const selectedBarcodeDataUri = variantOption.dataset.variantBarcodeDataUri || "";
  const selectedSourceLabel = variantOption.dataset.variantSourceValue || "";
  const selectedSourceType = variantOption.dataset.variantSourceType || "";
  const selectedSiteLinkStatusLabel = variantOption.dataset.variantSiteLinkStatusValue || "";
  const selectedHasSiteCandidate = variantOption.dataset.variantHasSiteCandidate === "1";
  const selectedCandidateConfirmHref = variantOption.dataset.variantCandidateConfirmHref || "";
  const selectedCandidateIgnoreHref = variantOption.dataset.variantCandidateIgnoreHref || "";
  const selectedCandidateCode = variantOption.dataset.variantCandidateCode || "";
  const selectedCandidateProductId = variantOption.dataset.variantCandidateProductId || "";
  const selectedCandidateConfidence = variantOption.dataset.variantCandidateConfidence || "";
  const selectedCandidateSignals = variantOption.dataset.variantCandidateSignals || "";
  const selectedStockQty = variantOption.dataset.variantStockQty || "0";
  const selectedIsSyncable = variantOption.dataset.variantIsSyncable === "1";

  variantRoot.querySelectorAll("[data-variant-option]").forEach((element) => {
    const labelElement = element.querySelector("[data-variant-option-label]");
    const fallbackLabel = element.dataset.variantLabel || "Variante";
    if (labelElement) {
      labelElement.textContent = fallbackLabel;
    } else {
      element.textContent = fallbackLabel;
    }
    element.setAttribute("aria-label", `Selecionar variante ${fallbackLabel}`);
  });

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

  variantRoot.querySelectorAll("[data-variant-save-button]").forEach((element) => {
    element.textContent = selectedSaveLabel;
    element.setAttribute("aria-pressed", selectedIsSaved ? "true" : "false");
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

  variantRoot.querySelectorAll("[data-variant-source-label]").forEach((element) => {
    element.textContent = selectedSourceLabel || "Site";
  });

  variantRoot.querySelectorAll("[data-variant-source-badge]").forEach((element) => {
    element.textContent = selectedSourceLabel || "Site";
    element.className = "status-badge";
    if (selectedSourceType === "legacy") {
      element.classList.add("status-badge--warning");
      return;
    }
    element.classList.add("status-badge--neutral");
  });

  variantRoot.querySelectorAll("[data-variant-site-link-status-label]").forEach((element) => {
    element.textContent = selectedSiteLinkStatusLabel || "Sem vínculo";
  });

  variantRoot.querySelectorAll("[data-variant-timestamp-label]").forEach((element) => {
    element.textContent = selectedTimestamp;
  });

  variantRoot.querySelectorAll("[data-variant-stock-label]").forEach((element) => {
    if (element.textContent.trim().toLowerCase().startsWith("estoque")) {
      element.textContent = `Estoque ${selectedStockQty || "0"}`;
      return;
    }
    element.textContent = selectedStockQty || "0";
  });

  variantRoot.querySelectorAll("[data-variant-copy-trigger]").forEach((element) => {
    element.setAttribute("data-copy-text", selectedVariantCode);
  });

  variantRoot.querySelectorAll("[data-variant-confirm-link-form]").forEach((element) => {
    if (selectedCandidateConfirmHref) {
      element.setAttribute("action", selectedCandidateConfirmHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-ignore-link-form]").forEach((element) => {
    if (selectedCandidateIgnoreHref) {
      element.setAttribute("action", selectedCandidateIgnoreHref);
    }
  });

  variantRoot.querySelectorAll("[data-variant-sync-action]").forEach((element) => {
    element.hidden = !selectedIsSyncable;
  });

  variantRoot.querySelectorAll("[data-variant-product-link-wrapper]").forEach((element) => {
    element.hidden = !selectedProductUrl;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-panel]").forEach((element) => {
    element.hidden = !selectedHasSiteCandidate;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-code]").forEach((element) => {
    element.textContent = selectedCandidateCode;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-product-id]").forEach((element) => {
    element.textContent = selectedCandidateProductId;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-confidence]").forEach((element) => {
    element.textContent = selectedCandidateConfidence;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-signals]").forEach((element) => {
    element.textContent = selectedCandidateSignals;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-code-row]").forEach((element) => {
    element.hidden = !selectedCandidateCode;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-product-id-row]").forEach((element) => {
    element.hidden = !selectedCandidateProductId;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-confidence-row]").forEach((element) => {
    element.hidden = !selectedCandidateConfidence;
  });

  variantRoot.querySelectorAll("[data-variant-candidate-signals-row]").forEach((element) => {
    element.hidden = !selectedCandidateSignals;
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

function syncSourceTypeFields(formRoot) {
  /*
    Responsabilidade:
      Ajustar a visibilidade dos blocos do formulario conforme a origem escolhida.

    Parametros:
      formRoot: Formulario que concentra radios e blocos condicionais.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantem o mesmo HTML para site, manual e legado, mas reduz ruido visual
      quando o operador escolhe um cadastro que nao depende do site.
  */

  if (!formRoot) {
    return;
  }

  const selectedField = formRoot.querySelector("[data-source-type-field]:checked");
  const selectedSourceType = selectedField?.value || "site";
  const supportsManualFields = selectedSourceType === "manual" || selectedSourceType === "legacy";

  formRoot.querySelectorAll("[data-source-type-field]").forEach((field) => {
    field.closest(".source-switch__option")?.classList.toggle("source-switch__option--active", field.checked);
  });

  formRoot.querySelectorAll("[data-site-field], [data-site-single-variant]").forEach((element) => {
    const shouldStayVisible = !supportsManualFields;
    element.hidden = !shouldStayVisible;
    toggleSectionFieldAvailability(element, shouldStayVisible);
  });

  formRoot.querySelectorAll("[data-manual-variants-section]").forEach((element) => {
    const shouldStayVisible = supportsManualFields;
    element.hidden = !shouldStayVisible;
    toggleSectionFieldAvailability(element, shouldStayVisible);
  });
}

function toggleSectionFieldAvailability(sectionElement, isEnabled) {
  /*
    Responsabilidade:
      Habilitar apenas os campos do bloco atualmente ativo no formulário.

    Parametros:
      sectionElement: Bloco visual que contém inputs relacionados.
      isEnabled: Indica se os campos internos devem participar do submit.

    Retorno:
      Nenhum.

    Contexto de uso:
      O formulário reutiliza campos de site e manual na mesma página. Ao
      desabilitar o bloco oculto, evitamos que valores escondidos disputem
      com a linha visível da variante e gerem salvamentos inconsistentes.
  */

  if (!sectionElement) {
    return;
  }

  sectionElement.querySelectorAll("input, select, textarea, button").forEach((field) => {
    if (field.hasAttribute("data-keep-enabled")) {
      field.disabled = false;
      return;
    }

    field.disabled = !isEnabled;
  });
}

function clearVariantRowInputs(variantRow) {
  /*
    Responsabilidade:
      Limpar os campos de uma linha de variante sem remover a estrutura HTML.

    Parametros:
      variantRow: Linha visual da variante a ser reiniciada.

    Retorno:
      Nenhum.

    Contexto de uso:
      Evita deixar o formulario sem nenhuma linha visivel quando o operador
      remove a ultima variante manual cadastrada na tela.
  */

  if (!variantRow) {
    return;
  }

  variantRow.querySelectorAll("input").forEach((input) => {
    if (input.type === "number") {
      input.value = "0";
      return;
    }

    if (input.type === "file") {
      input.value = "";
      return;
    }

    input.value = "";
  });
}

function initializeManualProductForm() {
  /*
    Responsabilidade:
      Ativar comportamentos leves do formulario de cadastro manual.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Permite adicionar/remover variantes e alternar origem sem reescrever o
      fluxo server-side existente nem depender de frameworks adicionais.
  */

  const formRoot = document.querySelector("[data-manual-product-form]");
  if (!formRoot) {
    return;
  }

  syncSourceTypeFields(formRoot);

  formRoot.querySelectorAll("[data-source-type-field]").forEach((field) => {
    field.addEventListener("change", () => {
      syncSourceTypeFields(formRoot);
    });
  });

  const variantList = formRoot.querySelector("[data-manual-variant-list]");
  const variantTemplate = formRoot.querySelector("[data-manual-variant-template]");
  const addVariantButton = formRoot.querySelector("[data-add-variant-row]");

  if (variantList && variantTemplate && addVariantButton) {
    addVariantButton.addEventListener("click", () => {
      const fragment = variantTemplate.content.cloneNode(true);
      variantList.appendChild(fragment);
    });

    variantList.addEventListener("click", (event) => {
      const removeButton = event.target.closest("[data-remove-variant-row]");
      if (!removeButton) {
        return;
      }

      const variantRows = variantList.querySelectorAll("[data-manual-variant-row]");
      const variantRow = removeButton.closest("[data-manual-variant-row]");
      if (!variantRow) {
        return;
      }

      if (variantRows.length <= 1) {
        clearVariantRowInputs(variantRow);
        return;
      }

      variantRow.remove();
    });
  }
}

function updateImagePreview(targetKey, imageUrl) {
  /*
    Responsabilidade:
      Exibir ou ocultar previews de imagem vinculados ao formulario.

    Parametros:
      targetKey: Identificador logico do preview, como `product`.
      imageUrl: URL temporaria gerada pelo navegador para o arquivo selecionado.

    Retorno:
      Nenhum.

    Contexto de uso:
      Ajuda o operador mobile a confirmar rapidamente a foto escolhida antes
      de persistir o cadastro manual.
  */

  const previewImage = document.querySelector(`[data-image-preview-image="${targetKey}"]`);
  const previewEmpty = document.querySelector(`[data-image-preview-empty="${targetKey}"]`);
  if (!previewImage) {
    return;
  }

  if (!imageUrl) {
    previewImage.setAttribute("hidden", "hidden");
    previewImage.removeAttribute("src");
    if (previewEmpty) {
      previewEmpty.hidden = false;
    }
    return;
  }

  previewImage.removeAttribute("hidden");
  previewImage.setAttribute("src", imageUrl);
  if (previewEmpty) {
    previewEmpty.hidden = true;
  }
}

function initializeImageInputPreviews() {
  /*
    Responsabilidade:
      Conectar inputs de arquivo ao preview visual imediato das imagens.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantem o fluxo manual amigavel no celular, onde a confirmacao visual da
      foto escolhida evita cadastros com imagem errada.
  */

  document.querySelectorAll("[data-image-preview-input]").forEach((input) => {
    input.addEventListener("change", () => {
      const targetKey = input.dataset.imagePreviewTarget || "";
      const selectedFile = input.files?.[0];
      if (!targetKey || !selectedFile) {
        updateImagePreview(targetKey, "");
        return;
      }

      const objectUrl = window.URL.createObjectURL(selectedFile);
      updateImagePreview(targetKey, objectUrl);
    });
  });
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

function setCreateMenuState(createRoot, shouldOpen) {
  /*
    Responsabilidade:
      Sincronizar o estado visual e acessível do menu de criação do header.

    Parametros:
      createRoot: Container raiz que concentra botão e atalhos rápidos.
      shouldOpen: Define se o menu deve ficar aberto ou fechado.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantém o comportamento do botão de criar previsível no mobile sem
      depender de bibliotecas externas nem afetar o fluxo principal do app.
  */

  if (!createRoot) {
    return;
  }

  const trigger = createRoot.querySelector("[data-create-trigger]");
  if (!trigger) {
    return;
  }

  createRoot.dataset.open = shouldOpen ? "true" : "false";
  trigger.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
}

function initializeCreateMenu() {
  /*
    Responsabilidade:
      Ativar o botão de criação do header com menu rápido de atalhos.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantém a ação principal de criar no topo da interface sem depender de
      um FAB separado, reduzindo ruído visual no shell do app.
  */

  const createRoot = document.querySelector("[data-create-root]");
  const createTrigger = createRoot?.querySelector("[data-create-trigger]");
  if (!createRoot || !createTrigger) {
    return;
  }

  setCreateMenuState(createRoot, false);

  createTrigger.addEventListener("click", () => {
    const isOpen = createRoot.dataset.open === "true";
    setCreateMenuState(createRoot, !isOpen);
  });

  document.addEventListener("click", (event) => {
    if (!createRoot.contains(event.target)) {
      setCreateMenuState(createRoot, false);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setCreateMenuState(createRoot, false);
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
initializeCreateMenu();
initializeManualProductForm();
initializeImageInputPreviews();
