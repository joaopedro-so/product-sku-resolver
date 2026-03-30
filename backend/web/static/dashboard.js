/*
  Decisao tecnica:
  Este arquivo adiciona apenas interacoes operacionais leves. A ideia e manter
  o dashboard funcional mesmo sem JavaScript, usando o script apenas para
  copiar SKU e compartilhar links quando o navegador oferecer suporte.
*/
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
      window.alert(`Nao foi possivel copiar o SKU: ${error}`);
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
      window.alert("Link copiado para a area de transferencia.");
    } catch (error) {
      window.alert(`Nao foi possivel compartilhar: ${error}`);
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
