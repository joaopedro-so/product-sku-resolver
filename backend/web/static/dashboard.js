/*
  Decisao tecnica:
  Este arquivo adiciona apenas interacoes operacionais leves. A ideia e manter
  o dashboard funcional mesmo sem JavaScript, usando o script para copiar
  codigo da variante, compartilhar links e alternar variantes sem navegar.
*/

let activeToastTimeoutId = 0;
let activeSyncJobPollerId = 0;

function showAppToast(messageText, tone = "neutral") {
  /*
    Responsabilidade:
      Exibir um feedback global curto e nao modal para a operacao atual.

    Parametros:
      messageText: Texto objetivo que explica o resultado da acao.
      tone: Tom visual do toast, como `success`, `error` ou `neutral`.

    Retorno:
      Nenhum.

    Contexto de uso:
      O app precisa confirmar copias, compartilhamentos e pequenas falhas sem
      interromper o fluxo com alertas modais. O toast global reaproveita o
      shell existente e reduz atrito em uso repetitivo no celular.
  */

  const toastElement = document.querySelector("[data-app-toast]");
  if (!(toastElement instanceof HTMLElement) || !messageText) {
    return;
  }

  toastElement.hidden = false;
  toastElement.textContent = messageText;
  toastElement.className = "app-toast";
  toastElement.classList.add(`app-toast--${tone || "neutral"}`);

  if (activeToastTimeoutId) {
    window.clearTimeout(activeToastTimeoutId);
  }

  activeToastTimeoutId = window.setTimeout(() => {
    toastElement.hidden = true;
    toastElement.textContent = "";
    toastElement.className = "app-toast";
  }, 2400);
}

function showTemporaryButtonLabel(buttonElement, temporaryLabel, durationInMilliseconds = 1200) {
  /*
    Responsabilidade:
      Trocar o rotulo de um botao por alguns instantes sem perder o texto original.

    Parametros:
      buttonElement: Botao visual que recebera o feedback temporario.
      temporaryLabel: Texto curto usado como confirmacao imediata.
      durationInMilliseconds: Janela de tempo antes de restaurar o rotulo.

    Retorno:
      Nenhum.

    Contexto de uso:
      Reforca microinteracoes como copiar codigo sem depender apenas do toast
      global. Assim o operador percebe o sucesso tanto no contexto local quanto
      no shell do aplicativo.
  */

  if (!(buttonElement instanceof HTMLElement) || !temporaryLabel) {
    return;
  }

  if (!buttonElement.dataset.originalLabel) {
    buttonElement.dataset.originalLabel = buttonElement.textContent || "";
  }

  buttonElement.textContent = temporaryLabel;
  window.setTimeout(() => {
    buttonElement.textContent = buttonElement.dataset.originalLabel || buttonElement.textContent;
  }, durationInMilliseconds);
}

function focusFieldWithoutScroll(targetElement, shouldSelectText = false) {
  /*
    Responsabilidade:
      Aplicar foco contextual sem provocar saltos extras de scroll na pagina.

    Parametros:
      targetElement: Campo que deve receber foco.
      shouldSelectText: Define se o texto atual do input deve ser selecionado.

    Retorno:
      Nenhum.

    Contexto de uso:
      A UX pede autofocus apenas quando ele realmente acelera a tarefa. Usamos
      `preventScroll` para respeitar o contexto atual e evitar que a tela
      "roube" a posicao do operador em navegacao mobile.
  */

  if (!(targetElement instanceof HTMLElement)) {
    return;
  }

  window.requestAnimationFrame(() => {
    targetElement.focus({ preventScroll: true });
    if (shouldSelectText && typeof targetElement.select === "function") {
      targetElement.select();
    }
  });
}

function normalizeSyncJobSnapshot(rawSnapshot) {
  /*
    Responsabilidade:
      Validar e normalizar o payload bruto de um job de sincronizacao.

    Parametros:
      rawSnapshot: Objeto vindo do HTML inicial ou do endpoint de polling.

    Retorno:
      Objeto padronizado com defaults seguros para a UI.

    Contexto de uso:
      O frontend precisa renderizar progresso mesmo quando parte dos campos
      ainda nao chegou. Esta normalizacao evita `undefined` espalhado pelo DOM.
  */

  if (!rawSnapshot || typeof rawSnapshot !== "object") {
    return null;
  }

  return {
    job_id: String(rawSnapshot.job_id || ""),
    status: String(rawSnapshot.status || ""),
    total: Number(rawSnapshot.total || 0),
    processed: Number(rawSnapshot.processed || 0),
    updated: Number(rawSnapshot.updated || 0),
    unchanged: Number(rawSnapshot.unchanged || 0),
    failed: Number(rawSnapshot.failed || 0),
    skipped: Number(rawSnapshot.skipped || 0),
    current_item: String(rawSnapshot.current_item || ""),
    started_at: String(rawSnapshot.started_at || ""),
    finished_at: String(rawSnapshot.finished_at || ""),
    error_message: String(rawSnapshot.error_message || ""),
    percentage_complete: Number(rawSnapshot.percentage_complete || 0),
    is_active: rawSnapshot.is_active === true,
    is_finished: rawSnapshot.is_finished === true,
  };
}

function buildSyncJobStatusLabel(syncJobSnapshot) {
  /*
    Responsabilidade:
      Traduzir o status tecnico do job em um rotulo curto para o painel.

    Parametros:
      syncJobSnapshot: Snapshot normalizado do job atual.

    Retorno:
      Texto curto, como `Sincronizando agora` ou `Sincronizacao concluida`.

    Contexto de uso:
      O painel de progresso precisa comunicar estado de forma confiavel sem
      expor termos tecnicos crus como `queued` ou `completed`.
  */

  if (!syncJobSnapshot) {
    return "Sincronizacao";
  }

  if (syncJobSnapshot.status === "queued") {
    return "Sincronizacao na fila";
  }

  if (syncJobSnapshot.status === "running") {
    return "Sincronizando agora";
  }

  if (syncJobSnapshot.status === "completed") {
    return "Sincronizacao concluida";
  }

  if (syncJobSnapshot.status === "failed") {
    return "Falha no lote";
  }

  return "Sincronizacao";
}

function buildSyncJobSummaryText(syncJobSnapshot) {
  /*
    Responsabilidade:
      Gerar o resumo principal do progresso no formato operacional esperado.

    Parametros:
      syncJobSnapshot: Snapshot normalizado do job atual.

    Retorno:
      Texto curto como `63 de 148 itens processados`.

    Contexto de uso:
      O operador precisa bater o olho e saber o quanto do lote ja andou sem
      interpretar varias metricas separadas.
  */

  if (!syncJobSnapshot) {
    return "0 de 0 itens processados";
  }

  return `${syncJobSnapshot.processed} de ${syncJobSnapshot.total} itens processados`;
}

function buildSyncJobCountsText(syncJobSnapshot) {
  /*
    Responsabilidade:
      Montar a linha resumida com alterados, sem mudanca, falhas e ignorados.

    Parametros:
      syncJobSnapshot: Snapshot normalizado do job atual.

    Retorno:
      Texto curto com as contagens mais relevantes do lote.

    Contexto de uso:
      Complementa a barra de progresso com transparencia sobre o tipo de
      resultado que o job esta produzindo, sem exigir abrir outra tela.
  */

  if (!syncJobSnapshot) {
    return "0 alterados • 0 sem mudanca • 0 falhas";
  }

  const lineParts = [
    `${syncJobSnapshot.updated} alterados`,
    `${syncJobSnapshot.unchanged} sem mudanca`,
    `${syncJobSnapshot.failed} falhas`,
  ];

  if (syncJobSnapshot.skipped > 0) {
    lineParts.push(`${syncJobSnapshot.skipped} ignorados`);
  }

  return lineParts.join(" • ");
}

function buildSyncJobResultText(syncJobSnapshot) {
  /*
    Responsabilidade:
      Gerar a mensagem final mostrada quando o job termina.

    Parametros:
      syncJobSnapshot: Snapshot normalizado do job atual.

    Retorno:
      Texto final de sucesso ou falha do lote.

    Contexto de uso:
      O painel de updates precisa encerrar o fluxo com um resumo claro para o
      operador confiar que o job terminou e saber o saldo final da rodada.
  */

  if (!syncJobSnapshot || !syncJobSnapshot.is_finished) {
    return "";
  }

  if (syncJobSnapshot.status === "failed") {
    return syncJobSnapshot.error_message || "O lote terminou com falha antes de concluir todos os itens.";
  }

  return `Lote concluido: ${buildSyncJobCountsText(syncJobSnapshot)}.`;
}

function renderSyncJobSnapshot(syncJobRoot, rawSnapshot) {
  /*
    Responsabilidade:
      Atualizar toda a area visual de progresso a partir do snapshot atual.

    Parametros:
      syncJobRoot: Card principal da tela de updates.
      rawSnapshot: Snapshot bruto ou normalizado do job.

    Retorno:
      Snapshot normalizado usado na renderizacao.

    Contexto de uso:
      Centraliza a sincronizacao entre barra, metricas, contadores, texto do
      item atual e estado do botao `Atualizar todos`.
  */

  if (!(syncJobRoot instanceof HTMLElement)) {
    return null;
  }

  const syncJobSnapshot = normalizeSyncJobSnapshot(rawSnapshot);
  const progressPanel = syncJobRoot.querySelector("[data-sync-progress-panel]");
  const startButton = syncJobRoot.querySelector("[data-sync-job-start-button]");
  const metricChecked = syncJobRoot.querySelector("[data-sync-metric-checked]");
  const metricChanged = syncJobRoot.querySelector("[data-sync-metric-changed]");
  const metricFailed = syncJobRoot.querySelector("[data-sync-metric-failed]");
  const lastCycleLabel = syncJobRoot.querySelector("[data-sync-last-cycle-label]");
  const statusLabel = syncJobRoot.querySelector("[data-sync-job-status-label]");
  const percentageLabel = syncJobRoot.querySelector("[data-sync-job-percentage]");
  const progressBarFill = syncJobRoot.querySelector("[data-sync-job-progress-bar]");
  const summaryText = syncJobRoot.querySelector("[data-sync-job-summary-text]");
  const countsText = syncJobRoot.querySelector("[data-sync-job-counts-text]");
  const currentItemText = syncJobRoot.querySelector("[data-sync-job-current-item]");
  const resultText = syncJobRoot.querySelector("[data-sync-job-result-text]");

  if (!(startButton instanceof HTMLElement)) {
    return syncJobSnapshot;
  }

  if (!startButton.dataset.defaultLabel) {
    startButton.dataset.defaultLabel = startButton.textContent || "Atualizar todos";
  }

  if (!syncJobSnapshot) {
    if (progressPanel instanceof HTMLElement) {
      progressPanel.hidden = true;
    }
    startButton.removeAttribute("disabled");
    startButton.classList.remove("button--busy");
    startButton.textContent = startButton.dataset.defaultLabel || "Atualizar todos";
    return null;
  }

  syncJobRoot.dataset.syncJobId = syncJobSnapshot.job_id;

  if (progressPanel instanceof HTMLElement) {
    progressPanel.hidden = false;
  }

  if (statusLabel instanceof HTMLElement) {
    statusLabel.textContent = buildSyncJobStatusLabel(syncJobSnapshot);
  }

  if (percentageLabel instanceof HTMLElement) {
    percentageLabel.textContent = `${syncJobSnapshot.percentage_complete}%`;
  }

  if (progressBarFill instanceof HTMLElement) {
    progressBarFill.style.width = `${syncJobSnapshot.percentage_complete}%`;
  }

  if (summaryText instanceof HTMLElement) {
    summaryText.textContent = buildSyncJobSummaryText(syncJobSnapshot);
  }

  if (countsText instanceof HTMLElement) {
    countsText.textContent = buildSyncJobCountsText(syncJobSnapshot);
  }

  if (currentItemText instanceof HTMLElement) {
    currentItemText.hidden = !syncJobSnapshot.current_item || syncJobSnapshot.is_finished;
    currentItemText.textContent = syncJobSnapshot.current_item
      ? `Processando agora: ${syncJobSnapshot.current_item}`
      : "";
  }

  if (resultText instanceof HTMLElement) {
    const finalMessage = buildSyncJobResultText(syncJobSnapshot);
    resultText.hidden = !finalMessage;
    resultText.textContent = finalMessage;
    resultText.classList.toggle("sync-progress-card__result--error", syncJobSnapshot.status === "failed");
  }

  if (metricChecked instanceof HTMLElement) {
    metricChecked.textContent = syncJobSnapshot.total > 0
      ? `${syncJobSnapshot.processed}/${syncJobSnapshot.total}`
      : "0";
  }

  if (metricChanged instanceof HTMLElement) {
    metricChanged.textContent = String(syncJobSnapshot.updated);
  }

  if (metricFailed instanceof HTMLElement) {
    metricFailed.textContent = String(syncJobSnapshot.failed);
  }

  if (lastCycleLabel instanceof HTMLElement) {
    if (syncJobSnapshot.is_active) {
      lastCycleLabel.textContent = "Sincronizacao em andamento";
    } else if (syncJobSnapshot.status === "completed") {
      lastCycleLabel.textContent = "Sincronizacao concluida agora";
    } else if (syncJobSnapshot.status === "failed") {
      lastCycleLabel.textContent = "Ultimo lote terminou com falha";
    }
  }

  if (syncJobSnapshot.is_active) {
    startButton.setAttribute("disabled", "disabled");
    startButton.classList.add("button--busy");
    startButton.textContent = "Sincronizando...";
  } else {
    startButton.removeAttribute("disabled");
    startButton.classList.remove("button--busy");
    startButton.textContent = syncJobSnapshot.status === "failed" ? "Tentar novamente" : "Atualizar novamente";
  }

  return syncJobSnapshot;
}

function stopSyncJobPolling() {
  /*
    Responsabilidade:
      Encerrar o polling ativo do job de sincronizacao, quando existir.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Evita timers duplicados quando o operador inicia novo job ou recarrega a
      pagina de updates enquanto um polling anterior ainda estava agendado.
  */

  if (activeSyncJobPollerId) {
    window.clearTimeout(activeSyncJobPollerId);
    activeSyncJobPollerId = 0;
  }
}

function persistSyncJobQueryParameter(syncJobId) {
  /*
    Responsabilidade:
      Persistir o `job_id` atual na URL sem recarregar a pagina.

    Parametros:
      syncJobId: Identificador do job que deve ficar visivel na query string.

    Retorno:
      Nenhum.

    Contexto de uso:
      Se o operador navegar dentro do app e voltar para Updates, a tela consegue
      recuperar o snapshot correto do job ainda em andamento ou do ultimo lote.
  */

  if (!syncJobId || !window.history?.replaceState) {
    return;
  }

  const currentUrl = new URL(window.location.href);
  currentUrl.searchParams.set("job_id", syncJobId);
  window.history.replaceState({}, "", currentUrl.toString());
}

function scheduleSyncJobPolling(syncJobRoot, syncJobId) {
  /*
    Responsabilidade:
      Consultar periodicamente o endpoint de status do job ate sua conclusao.

    Parametros:
      syncJobRoot: Card principal da tela de updates.
      syncJobId: Identificador do job que sera acompanhado.

    Retorno:
      Nenhum.

    Contexto de uso:
      Implementa a UX de progresso vivo da aba Updates sem exigir websocket ou
      SSE, reaproveitando o contrato simples de polling em JSON.
  */

  if (!(syncJobRoot instanceof HTMLElement) || !syncJobId) {
    return;
  }

  const statusUrlTemplate = syncJobRoot.dataset.syncJobStatusUrlTemplate || "";
  if (!statusUrlTemplate) {
    return;
  }

  stopSyncJobPolling();

  const pollOnce = async () => {
    try {
      const statusResponse = await window.fetch(
        statusUrlTemplate.replace("__JOB_ID__", encodeURIComponent(syncJobId)),
        { headers: { Accept: "application/json" } },
      );
      if (!statusResponse.ok) {
        throw new Error("Nao foi possivel consultar o status do job.");
      }

      const statusPayload = await statusResponse.json();
      const syncJobSnapshot = renderSyncJobSnapshot(syncJobRoot, statusPayload.job || {});
      if (syncJobSnapshot?.is_active) {
        activeSyncJobPollerId = window.setTimeout(pollOnce, 1200);
        return;
      }

      stopSyncJobPolling();
    } catch (error) {
      stopSyncJobPolling();
      showAppToast("Nao foi possivel atualizar o progresso do sync.", "error");
    }
  };

  activeSyncJobPollerId = window.setTimeout(pollOnce, 1200);
}

function initializeSyncJobProgress() {
  /*
    Responsabilidade:
      Ativar o fluxo assíncrono da tela de updates com start e polling.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      Substitui o antigo POST bloqueante por um job em background, mantendo a
      mesma tela atualizada com barra de progresso, contagens e item corrente.
  */

  const syncJobRoot = document.querySelector("[data-sync-job-root]");
  if (!(syncJobRoot instanceof HTMLElement)) {
    return;
  }

  const initialStateElement = syncJobRoot.querySelector("[data-sync-job-initial-state]");
  let initialSnapshot = null;
  if (initialStateElement instanceof HTMLScriptElement && initialStateElement.textContent) {
    try {
      initialSnapshot = JSON.parse(initialStateElement.textContent);
    } catch (error) {
      initialSnapshot = null;
    }
  }

  let latestRenderedSnapshot = renderSyncJobSnapshot(syncJobRoot, initialSnapshot);
  if (latestRenderedSnapshot?.job_id) {
    persistSyncJobQueryParameter(latestRenderedSnapshot.job_id);
  }
  if (latestRenderedSnapshot?.is_active) {
    scheduleSyncJobPolling(syncJobRoot, latestRenderedSnapshot.job_id);
  }

  const startForm = syncJobRoot.querySelector("[data-sync-job-start-form]");
  if (!(startForm instanceof HTMLFormElement)) {
    return;
  }

  startForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const startButton = syncJobRoot.querySelector("[data-sync-job-start-button]");
    const startUrl = startForm.dataset.syncJobStartUrl || "";
    if (!startUrl || !(startButton instanceof HTMLElement) || startButton.hasAttribute("disabled")) {
      return;
    }

    const previousSnapshot = latestRenderedSnapshot;
    startButton.setAttribute("disabled", "disabled");
    startButton.classList.add("button--busy");
    startButton.textContent = "Iniciando...";

    try {
      const startResponse = await window.fetch(startUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
        },
      });
      if (!startResponse.ok) {
        throw new Error("Nao foi possivel iniciar a sincronizacao em lote.");
      }

      const startPayload = await startResponse.json();
      const syncJobSnapshot = renderSyncJobSnapshot(syncJobRoot, startPayload.job || {});
      if (!syncJobSnapshot?.job_id) {
        throw new Error("O job foi iniciado sem identificador valido.");
      }

      latestRenderedSnapshot = syncJobSnapshot;
      persistSyncJobQueryParameter(syncJobSnapshot.job_id);
      scheduleSyncJobPolling(syncJobRoot, syncJobSnapshot.job_id);
      showAppToast(
        startPayload.started_new_job === false
          ? "Um lote ja estava em andamento. Progresso retomado."
          : "Sincronizacao em lote iniciada.",
        "success",
      );
      if (initialStateElement instanceof HTMLScriptElement) {
        initialStateElement.textContent = JSON.stringify(startPayload.job || {});
      }
    } catch (error) {
      latestRenderedSnapshot = renderSyncJobSnapshot(syncJobRoot, previousSnapshot);
      showAppToast("Nao foi possivel iniciar o sync em lote.", "error");
    }
  });
}

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
  const selectedSaveLabel =
    variantOption.dataset.variantSaveLabel ||
    (selectedIsSaved ? "Remover do acesso rápido" : "Adicionar ao acesso rápido");
  const selectedProductUrl = variantOption.dataset.variantProductUrl || "";
  const selectedImageUrl = variantOption.dataset.variantImageUrl || "";
  const selectedStatusKey = variantOption.dataset.variantStatusKey || "";
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

  const supportLineShouldShowStatus = shouldDisplayVariantStatusInSupportLine(selectedStatusKey);
  variantRoot.querySelectorAll("[data-variant-support-status-label]").forEach((element) => {
    element.hidden = !supportLineShouldShowStatus;
  });

  variantRoot.querySelectorAll("[data-variant-support-stock-label]").forEach((element) => {
    element.hidden = Number(selectedStockQty || "0") <= 0;
  });

  variantRoot.querySelectorAll("[data-variant-support-line]").forEach((element) => {
    const hasVisibleChild = Array.from(element.children).some((childElement) => !childElement.hidden);
    element.hidden = !hasVisibleChild;
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

  syncInlineBarcodeContent(variantRoot);

  const storageKey = variantRoot.dataset.variantStorageKey || "";
  if (storageKey && selectedAlias) {
    window.localStorage.setItem(storageKey, selectedAlias);
  }
}

function shouldDisplayVariantStatusInSupportLine(statusKey) {
  /*
    Responsabilidade:
      Definir quando o resumo de status merece aparecer no card colapsado.

    Parametros:
      statusKey: Chave interna do estado operacional da variante ativa.

    Retorno:
      `true` quando o status precisa chamar atenção no card; `false` quando ele
      só adicionaria ruído visual ao fluxo de bipagem.

    Contexto de uso:
      Busca e prateleira devem priorizar nome, variante e acesso ao código.
      Estados neutros como "sem sync" ou "sem mudança" só entram em telas mais
      profundas; no card, mostramos apenas situações que pedem decisão rápida.
  */

  return ["candidate_found", "manual_ok", "manual_error", "changed", "failed"].includes(String(statusKey || ""));
}

function setInlineBarcodePanelState(inlineBarcodeCard, shouldOpen) {
  /*
    Responsabilidade:
      Abrir ou fechar o painel inline de codigo dentro do card da prateleira.

    Parametros:
      inlineBarcodeCard: Card do produto que concentra o painel expansivel.
      shouldOpen: Estado desejado para o painel do card.

    Retorno:
      Nenhum.

    Contexto de uso:
      A leitura do codigo precisa acontecer sem tirar o operador da lista da
      prateleira. Esta funcao centraliza o estado visual e acessivel do card.
  */

  if (!inlineBarcodeCard) {
    return;
  }

  const inlineBarcodePanel = inlineBarcodeCard.querySelector("[data-inline-barcode-panel]");
  const toggleButton = inlineBarcodeCard.querySelector("[data-inline-barcode-toggle]");
  if (!inlineBarcodePanel || !toggleButton) {
    return;
  }

  if (!toggleButton.dataset.closedLabel) {
    toggleButton.dataset.closedLabel = toggleButton.textContent || "Código";
  }

  inlineBarcodeCard.classList.toggle("shelf-product-card--barcode-open", shouldOpen);
  inlineBarcodeCard.dataset.inlineBarcodeOpen = shouldOpen ? "true" : "false";
  inlineBarcodePanel.hidden = !shouldOpen;
  toggleButton.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
  toggleButton.textContent = shouldOpen ? "Recolher" : toggleButton.dataset.closedLabel;
}

function closeOtherInlineBarcodePanels(currentCard) {
  /*
    Responsabilidade:
      Garantir que apenas um card de prateleira fique expandido por vez.

    Parametros:
      currentCard: Card que deve permanecer aberto, quando existir.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantem a lista leve no celular e evita que varios barcodes disputem
      espaco ao mesmo tempo durante a conferencia.
  */

  document.querySelectorAll("[data-inline-barcode-card]").forEach((card) => {
    if (card === currentCard) {
      return;
    }

    setInlineBarcodePanelState(card, false);
  });
}

function syncInlineBarcodeContent(variantRoot) {
  /*
    Responsabilidade:
      Sincronizar o bloco inline de barcode com a variante atualmente ativa.

    Parametros:
      variantRoot: Card ou detalhe que contem as opcoes de variante.

    Retorno:
      Nenhum.

    Contexto de uso:
      A prateleira precisa trocar codigo e barcode inline sem navegar. Esta
      rotina le a variante ativa e garante que o painel aberto continue fiel
      ao ml selecionado no card.
  */

  if (!variantRoot) {
    return;
  }

  const activeVariantOption = variantRoot.querySelector("[data-variant-option].variant-chip--active");
  if (!activeVariantOption) {
    return;
  }

  const selectedVariantCode = activeVariantOption.dataset.variantCode || "";
  const selectedBarcodeDataUri = activeVariantOption.dataset.variantBarcodeDataUri || "";

  variantRoot.querySelectorAll("[data-variant-barcode-image]").forEach((element) => {
    if (selectedBarcodeDataUri) {
      element.setAttribute("src", selectedBarcodeDataUri);
      element.setAttribute("alt", `Codigo de barras do codigo ${selectedVariantCode}`);
      return;
    }

    element.removeAttribute("src");
    element.setAttribute("alt", "Codigo de barras indisponivel");
  });

  variantRoot.querySelectorAll("[data-variant-barcode-image-frame]").forEach((element) => {
    element.hidden = !selectedBarcodeDataUri;
  });

  variantRoot.querySelectorAll("[data-variant-barcode-empty]").forEach((element) => {
    element.hidden = Boolean(selectedBarcodeDataUri);
  });
}

function initializeInlineBarcodePanels() {
  /*
    Responsabilidade:
      Transformar o CTA `Codigo` da prateleira em expansao inline do barcode.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      O fluxo principal do app agora prioriza bipagem: abrir o codigo dentro do
      proprio card, manter a prateleira visivel e so depois, se necessario,
      oferecer a tela cheia.
  */

  document.querySelectorAll("[data-inline-barcode-card]").forEach((inlineBarcodeCard) => {
    const toggleButton = inlineBarcodeCard.querySelector("[data-inline-barcode-toggle]");
    const closeButton = inlineBarcodeCard.querySelector("[data-inline-barcode-close]");
    if (!toggleButton) {
      return;
    }

    setInlineBarcodePanelState(inlineBarcodeCard, false);
    syncInlineBarcodeContent(inlineBarcodeCard);

    toggleButton.addEventListener("click", () => {
      const shouldOpen = inlineBarcodeCard.dataset.inlineBarcodeOpen !== "true";
      closeOtherInlineBarcodePanels(shouldOpen ? inlineBarcodeCard : null);
      setInlineBarcodePanelState(inlineBarcodeCard, shouldOpen);
      syncInlineBarcodeContent(inlineBarcodeCard);
    });

    closeButton?.addEventListener("click", () => {
      setInlineBarcodePanelState(inlineBarcodeCard, false);
    });
  });
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
  const allowsSiteVariants = formRoot.dataset.allowsSiteVariants === "true";
  const supportsVariantBatch = supportsManualFields || (selectedSourceType === "site" && allowsSiteVariants);

  formRoot.querySelectorAll("[data-source-type-field]").forEach((field) => {
    field.closest(".source-switch__option")?.classList.toggle("source-switch__option--active", field.checked);
  });

  formRoot.querySelectorAll("[data-site-field], [data-site-single-variant]").forEach((element) => {
    const shouldStayVisible = !supportsManualFields;
    element.hidden = !shouldStayVisible;
    toggleSectionFieldAvailability(element, shouldStayVisible);
  });

  formRoot.querySelectorAll("[data-site-variant-field]").forEach((element) => {
    const shouldStayVisible = !supportsManualFields;
    element.hidden = !shouldStayVisible;
    toggleSectionFieldAvailability(element, shouldStayVisible);
  });

  formRoot.querySelectorAll("[data-manual-variants-section]").forEach((element) => {
    const shouldStayVisible = supportsVariantBatch;
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

function readManualVariantFieldValue(variantRow, fieldName) {
  /*
    Responsabilidade:
      Ler de forma segura o valor textual principal de um campo da variante.

    Parametros:
      variantRow: Linha visual que concentra os inputs da variante.
      fieldName: Nome do campo HTML a ser consultado.

    Retorno:
      Texto normalizado sem espaços nas pontas. Retorna string vazia se o
      campo não existir.

    Contexto de uso:
      Centraliza a leitura dos campos do editor de variantes para que a
      camada visual monte títulos e resumos sem duplicar seletores.
  */

  if (!variantRow) {
    return "";
  }

  const field = variantRow.querySelector(`[name="${fieldName}"]`);
  if (!field || typeof field.value !== "string") {
    return "";
  }

  return field.value.trim();
}

function hasManualVariantImageSelection(variantRow) {
  /*
    Responsabilidade:
      Identificar se a linha da variante já possui uma imagem escolhida.

    Parametros:
      variantRow: Linha visual avaliada no formulário.

    Retorno:
      `true` quando existe arquivo selecionado ou alguma referência de imagem
      persistida na linha; `false` nos demais casos.

    Contexto de uso:
      O status visual da linha precisa considerar também imagens importadas,
      porque uma variante pode estar em edição mesmo antes de receber código.
  */

  if (!variantRow) {
    return false;
  }

  const fileField = variantRow.querySelector('[name="manual_variant_image"]');
  if (fileField && fileField.files && fileField.files.length > 0) {
    return true;
  }

  const persistedImageField = variantRow.querySelector('[name="manual_variant_image_url"]');
  return Boolean(persistedImageField && persistedImageField.value.trim());
}

function refreshManualVariantRowPresentation(variantList) {
  /*
    Responsabilidade:
      Atualizar títulos, estados e resumo visual das linhas de variante.

    Parametros:
      variantList: Container que agrupa todas as variantes do formulário.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantém a edição mais clara ao renumerar as linhas após adição/remoção e
      ao diferenciar visualmente uma variante preenchida de uma nova linha.
  */

  if (!variantList) {
    return;
  }

  const variantRows = Array.from(variantList.querySelectorAll("[data-manual-variant-row]"));

  variantRows.forEach((variantRow, index) => {
    const titleElement = variantRow.querySelector("[data-manual-variant-title]");
    const eyebrowElement = variantRow.querySelector(".manual-variant-row__eyebrow");
    const summaryElement = variantRow.querySelector("[data-manual-variant-summary]");
    const stateElement = variantRow.querySelector("[data-manual-variant-state]");
    const variantLabel = readManualVariantFieldValue(variantRow, "manual_variant_label");
    const variantCode = readManualVariantFieldValue(variantRow, "manual_variant_code");
    const variantAlias = readManualVariantFieldValue(variantRow, "manual_variant_alias");
    const variantNotes = readManualVariantFieldValue(variantRow, "manual_variant_notes");
    const rawStockQty = readManualVariantFieldValue(variantRow, "manual_variant_stock_qty");
    const hasSelectedImage = hasManualVariantImageSelection(variantRow);
    const hasMeaningfulStock = rawStockQty !== "" && rawStockQty !== "0";
    const hasMeaningfulData = Boolean(
      variantLabel || variantCode || variantAlias || variantNotes || hasMeaningfulStock || hasSelectedImage,
    );
    const sequenceLabel = `Variante ${index + 1}`;

    if (eyebrowElement) {
      eyebrowElement.textContent = sequenceLabel;
    }

    if (titleElement) {
      titleElement.textContent = sequenceLabel;
    }

    if (stateElement) {
      stateElement.textContent = hasMeaningfulData ? (variantLabel || "Em edição") : "Nova variante";
    }

    if (summaryElement) {
      if (!hasMeaningfulData) {
        summaryElement.textContent = "Preencha volume, código e estoque para incluir esta linha no grupo.";
      } else if (variantLabel && variantCode) {
        summaryElement.textContent = `${variantLabel} • código ${variantCode}`;
      } else if (variantLabel) {
        summaryElement.textContent = `${variantLabel} • complete o código e o estoque se necessário`;
      } else if (variantCode) {
        summaryElement.textContent = `Código ${variantCode} • defina o rótulo da variante`;
      } else {
        summaryElement.textContent = "Linha em edição • revise os campos antes de salvar";
      }
    }

    variantRow.classList.toggle("manual-variant-row--draft", !hasMeaningfulData);
  });
}

function revealManualVariantRow(variantRow) {
  /*
    Responsabilidade:
      Levar o operador até a variante recém-criada e destacar a nova linha.

    Parametros:
      variantRow: Linha visual recém-adicionada ao formulário.

    Retorno:
      Nenhum.

    Contexto de uso:
      Ao adicionar uma variante, o operador não deve procurar manualmente onde
      a nova seção apareceu. Esta rotina rola a tela, aplica destaque breve e
      foca o primeiro campo útil da linha.
  */

  if (!variantRow) {
    return;
  }

  variantRow.classList.add("manual-variant-row--highlighted");
  window.setTimeout(() => {
    variantRow.classList.remove("manual-variant-row--highlighted");
  }, 1800);

  variantRow.scrollIntoView({ behavior: "smooth", block: "center" });

  const firstInteractiveField = variantRow.querySelector(
    'input:not([type="hidden"]):not([type="file"]):not([disabled]), textarea:not([disabled]), select:not([disabled])',
  );
  if (firstInteractiveField instanceof HTMLElement) {
    window.requestAnimationFrame(() => {
      firstInteractiveField.focus({ preventScroll: true });
      if (typeof firstInteractiveField.select === "function" && firstInteractiveField instanceof HTMLInputElement) {
        firstInteractiveField.select();
      }
    });
  }
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
  syncSuggestedMatchName(formRoot);

  formRoot.querySelectorAll("[data-source-type-field]").forEach((field) => {
    field.addEventListener("change", () => {
      syncSourceTypeFields(formRoot);
    });
  });

  formRoot.querySelectorAll("[data-match-part]").forEach((field) => {
    field.addEventListener("input", () => {
      syncSuggestedMatchName(formRoot);
    });
    field.addEventListener("change", () => {
      syncSuggestedMatchName(formRoot);
    });
  });

  const matchNameField = formRoot.querySelector("[data-match-name-field]");
  if (matchNameField instanceof HTMLInputElement) {
    matchNameField.addEventListener("input", () => {
      const suggestedValue = composeSuggestedMatchName(formRoot);
      const currentValue = matchNameField.value.trim();
      const lastSuggestedValue = matchNameField.dataset.lastSuggestedValue || "";
      const matchesSuggestedValue = currentValue === suggestedValue || currentValue === lastSuggestedValue;
      matchNameField.dataset.userEdited = currentValue && !matchesSuggestedValue ? "true" : "false";
    });
  }

  const variantList = formRoot.querySelector("[data-manual-variant-list]");
  const variantTemplate = formRoot.querySelector("[data-manual-variant-template]");
  const addVariantButton = formRoot.querySelector("[data-add-variant-row]");

  if (variantList && variantTemplate && addVariantButton) {
    refreshManualVariantRowPresentation(variantList);

    addVariantButton.addEventListener("click", () => {
      const fragment = variantTemplate.content.cloneNode(true);
      variantList.appendChild(fragment);
      refreshManualVariantRowPresentation(variantList);
      const appendedRows = Array.from(variantList.querySelectorAll("[data-manual-variant-row]"));
      const newestRow = appendedRows[appendedRows.length - 1] || null;
      revealManualVariantRow(newestRow);
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
        refreshManualVariantRowPresentation(variantList);
        return;
      }

      variantRow.remove();
      refreshManualVariantRowPresentation(variantList);
    });

    const refreshRowState = (event) => {
      if (!event.target.closest("[data-manual-variant-row]")) {
        return;
      }

      refreshManualVariantRowPresentation(variantList);
    };

    variantList.addEventListener("input", refreshRowState);
    variantList.addEventListener("change", refreshRowState);
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

function initializeContextualAutofocus() {
  /*
    Responsabilidade:
      Aplicar foco automatico apenas nas telas em que isso reduz atrito real.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      A Home nao deve abrir teclado ao carregar, mas a busca vazia e o
      cadastro iniciado por ancora podem ganhar velocidade com foco imediato.
      Esta rotina centraliza as regras para evitar comportamentos agressivos.
  */

  const searchField = document.querySelector('[data-contextual-autofocus="search"]');
  if (searchField instanceof HTMLInputElement && searchField.dataset.autofocusEnabled === "true") {
    focusFieldWithoutScroll(searchField, false);
    return;
  }

  const manualProductForm = document.querySelector("[data-manual-product-form]");
  if (!(manualProductForm instanceof HTMLElement)) {
    return;
  }

  const formMode = manualProductForm.dataset.formMode || "create";
  const pageHash = window.location.hash || "";
  const autofillField = document.querySelector('[data-contextual-autofocus="autofill-url"]');
  const manualPrimaryField = manualProductForm.querySelector('[data-contextual-autofocus="manual-primary"]');

  if (formMode !== "edit") {
    if (pageHash === "#autofill" && autofillField instanceof HTMLInputElement) {
      focusFieldWithoutScroll(autofillField, false);
      return;
    }

    if (pageHash === "#manual" && manualPrimaryField instanceof HTMLInputElement) {
      focusFieldWithoutScroll(manualPrimaryField, true);
    }
    return;
  }

  if (pageHash && pageHash !== "#manual") {
    return;
  }

  if (manualPrimaryField instanceof HTMLInputElement) {
    focusFieldWithoutScroll(manualPrimaryField, true);
  }
}

function composeSuggestedMatchName(formRoot) {
  /*
    Responsabilidade:
      Montar um nome técnico sugerido a partir dos campos estruturados do formulário.

    Parametros:
      formRoot: Elemento raiz do formulário manual atualmente em edição.

    Retorno:
      String composta com marca, nome de exibição, tipo e variante principal.

    Contexto de uso:
      A operação precisa separar nome visual de nome técnico sem transformar o
      cadastro em trabalho duplicado. Esta sugestão cria um ponto de partida
      editável para busca e correspondência futura com o site.
  */

  if (!(formRoot instanceof HTMLElement)) {
    return "";
  }

  const readFieldValue = (selector) => {
    const field = formRoot.querySelector(selector);
    return field instanceof HTMLInputElement || field instanceof HTMLTextAreaElement || field instanceof HTMLSelectElement
      ? String(field.value || "").trim()
      : "";
  };

  const candidateParts = [
    readFieldValue('[data-match-part="brand"]'),
    readFieldValue('[data-match-part="display-name"]'),
    readFieldValue('[data-match-part="concentration"]'),
    readFieldValue('[data-match-part="variant"]'),
  ];

  return candidateParts.filter(Boolean).join(" ").trim();
}

function syncSuggestedMatchName(formRoot) {
  /*
    Responsabilidade:
      Preencher ou atualizar o nome técnico sugerido sem apagar edição manual.

    Parametros:
      formRoot: Elemento raiz do formulário manual atualmente em edição.

    Retorno:
      Nenhum.

    Contexto de uso:
      Mantém o formulário semanticamente correto: o nome de exibição continua
      humano, enquanto o nome de correspondência ganha uma sugestão útil para
      matching e religação com o site.
  */

  if (!(formRoot instanceof HTMLElement)) {
    return;
  }

  const matchNameField = formRoot.querySelector("[data-match-name-field]");
  if (!(matchNameField instanceof HTMLInputElement)) {
    return;
  }

  const suggestedValue = composeSuggestedMatchName(formRoot);
  const currentValue = matchNameField.value.trim();
  const lastSuggestedValue = matchNameField.dataset.lastSuggestedValue || "";
  const isUserEdited = matchNameField.dataset.userEdited === "true";

  if (!isUserEdited || !currentValue || currentValue === lastSuggestedValue) {
    matchNameField.value = suggestedValue;
    matchNameField.dataset.userEdited = "false";
  }

  matchNameField.dataset.lastSuggestedValue = suggestedValue;
}

function resolveSubmitBusyLabel(originalLabel) {
  /*
    Responsabilidade:
      Traduzir o rótulo atual do botão para uma versão de processamento.

    Parametros:
      originalLabel: Texto original do botão de submit acionado.

    Retorno:
      Rótulo curto e coerente com o tipo de ação em andamento.

    Contexto de uso:
      O app possui muitas ações rápidas de manutenção. Um feedback curto e
      contextual reduz ansiedade e evita toques repetidos durante o envio.
  */

  const normalizedLabel = String(originalLabel || "").trim().toLowerCase();
  if (!normalizedLabel) {
    return "Processando...";
  }

  if (normalizedLabel.includes("atualizar")) {
    return "Atualizando...";
  }

  if (normalizedLabel.includes("salvar") || normalizedLabel.includes("cadastrar")) {
    return "Salvando...";
  }

  if (normalizedLabel.includes("importar")) {
    return "Importando...";
  }

  if (normalizedLabel.includes("excluir")) {
    return "Excluindo...";
  }

  if (normalizedLabel.includes("vincular")) {
    return "Vinculando...";
  }

  if (normalizedLabel.includes("ignorar")) {
    return "Ignorando...";
  }

  return "Processando...";
}

function initializePostFormFeedback() {
  /*
    Responsabilidade:
      Bloquear envios duplicados e sinalizar processamento em formulários POST.

    Parametros:
      Nenhum.

    Retorno:
      Nenhum.

    Contexto de uso:
      A operação diária depende de cliques rápidos em salvar, atualizar,
      vincular e excluir. Esta rotina reduz toque duplo e deixa claro que a
      ação já foi enviada para o servidor.
  */

  document.querySelectorAll('form[method="post"]').forEach((formElement) => {
    if (formElement.dataset.skipGlobalSubmitFeedback === "true") {
      return;
    }

    formElement.addEventListener("submit", (event) => {
      if (formElement.dataset.submitting === "true") {
        event.preventDefault();
        return;
      }

      const submitTrigger =
        event.submitter ||
        formElement.querySelector('button[type="submit"], input[type="submit"]');
      if (!(submitTrigger instanceof HTMLElement)) {
        return;
      }

      formElement.dataset.submitting = "true";
      formElement.setAttribute("aria-busy", "true");

      const explicitBusyLabel =
        submitTrigger.getAttribute("data-submitting-label") ||
        formElement.getAttribute("data-submitting-label") ||
        "";
      const busyLabel = explicitBusyLabel || resolveSubmitBusyLabel(submitTrigger.textContent || "");

      formElement.querySelectorAll('button[type="submit"], input[type="submit"]').forEach((submitElement) => {
        submitElement.setAttribute("disabled", "disabled");
        submitElement.classList.add("button--busy");
      });

      if (!submitTrigger.dataset.originalLabel) {
        submitTrigger.dataset.originalLabel = submitTrigger.textContent || "";
      }
      submitTrigger.textContent = busyLabel;
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
      showTemporaryButtonLabel(copyTrigger, "Copiado");
      showAppToast("Codigo copiado.", "success");
    } catch (error) {
      showAppToast("Nao foi possivel copiar o codigo.", "error");
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
      showAppToast("Link copiado para a area de transferencia.", "success");
    } catch (error) {
      if (error instanceof Error && error.name === "AbortError") {
        return;
      }
      showAppToast("Nao foi possivel compartilhar o link.", "error");
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
initializeInlineBarcodePanels();
initializeCreateMenu();
initializeSyncJobProgress();
initializeManualProductForm();
initializeImageInputPreviews();
initializeContextualAutofocus();
initializePostFormFeedback();
