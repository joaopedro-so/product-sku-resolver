/*
  Decisao tecnica:
  Este service worker prioriza confiabilidade operacional. Ele nao tenta
  transformar o dashboard em app offline completo; apenas garante instalacao,
  abertura limpa em /dashboard e reaproveitamento seguro de paginas e assets
  criticos para reduzir falhas em reconexoes curtas.
*/

const DASHBOARD_PWA_CACHE_PREFIX = "prestigio-394-pwa";
const DASHBOARD_PWA_CACHE_VERSION = "v2026-04-07";
const DASHBOARD_PWA_STATIC_CACHE = `${DASHBOARD_PWA_CACHE_PREFIX}-static-${DASHBOARD_PWA_CACHE_VERSION}`;
const DASHBOARD_PWA_RUNTIME_CACHE = `${DASHBOARD_PWA_CACHE_PREFIX}-runtime-${DASHBOARD_PWA_CACHE_VERSION}`;
const DASHBOARD_PWA_OFFLINE_FALLBACK_URL = "/dashboard";
const DASHBOARD_PWA_PRECACHE_URLS = [
  "/dashboard",
  "/dashboard/search",
  "/dashboard/saved",
  "/dashboard/updates",
  "/dashboard/manifest.webmanifest",
  "/dashboard/static/brand/app-icon-192.png",
  "/dashboard/static/brand/app-icon-512.png",
];

self.addEventListener("install", handleInstallEvent);
self.addEventListener("activate", handleActivateEvent);
self.addEventListener("fetch", handleFetchEvent);

function handleInstallEvent(event) {
  /*
    Responsabilidade:
      Preaquecer o shell minimo do dashboard durante a instalacao.

    Parametros:
      event: Evento `install` disparado pelo navegador.

    Retorno:
      Nenhum; agenda promessas com `event.waitUntil`.

    Contexto de uso:
      O objetivo e garantir que o app instalado tenha ao menos a Home e as
      rotas principais disponiveis para abertura rapida e fallback offline.
  */

  event.waitUntil(
    Promise.all([
      precacheDashboardShell(),
      self.skipWaiting(),
    ]),
  );
}

function handleActivateEvent(event) {
  /*
    Responsabilidade:
      Remover caches antigos e assumir o controle das abas do dashboard.

    Parametros:
      event: Evento `activate` disparado apos uma nova versao assumir.

    Retorno:
      Nenhum; agenda promessas com `event.waitUntil`.

    Contexto de uso:
      Sem essa limpeza, deploys sucessivos acumulam versoes mortas de cache e
      tornam a atualizacao menos previsivel para quem usa o app instalado.
  */

  event.waitUntil(
    Promise.all([
      cleanupObsoleteDashboardCaches(),
      self.clients.claim(),
    ]),
  );
}

function handleFetchEvent(event) {
  /*
    Responsabilidade:
      Direcionar cada requisicao GET do dashboard para a estrategia adequada.

    Parametros:
      event: Evento `fetch` emitido para a requisicao atual.

    Retorno:
      Nenhum; injeta `event.respondWith` quando a requisicao deve ser tratada.

    Contexto de uso:
      Navegacoes HTML usam estrategia mais conservadora, enquanto assets
      estaticos priorizam velocidade e reuso de cache.
  */

  const request = event.request;
  if (!shouldHandleDashboardRequest(request)) {
    return;
  }

  const requestUrl = new URL(request.url);
  if (isDashboardNavigationRequest(request)) {
    event.respondWith(respondToDashboardNavigation(request));
    return;
  }

  if (isDashboardStaticRequest(requestUrl)) {
    event.respondWith(respondToDashboardStaticRequest(request, event));
    return;
  }

  event.respondWith(respondToDashboardRuntimeRequest(request));
}

function shouldHandleDashboardRequest(request) {
  /*
    Responsabilidade:
      Restringir o service worker ao escopo operacional relevante.

    Parametros:
      request: Requisicao emitida pela pagina ou pelo navegador.

    Retorno:
      `true` quando a requisicao e GET, same-origin e pertence a `/dashboard`.

    Contexto de uso:
      Mantemos o cache focado no painel interno para nao interferir em outros
      endpoints da aplicacao ou em recursos externos como fontes remotas.
  */

  if (!(request instanceof Request) || request.method !== "GET") {
    return false;
  }

  const requestUrl = new URL(request.url);
  if (requestUrl.origin !== self.location.origin) {
    return false;
  }

  if (requestUrl.pathname === "/dashboard/service-worker.js") {
    return false;
  }

  return requestUrl.pathname.startsWith("/dashboard");
}

function isDashboardNavigationRequest(request) {
  /*
    Responsabilidade:
      Identificar navegacoes HTML que precisam de fallback de abertura.

    Parametros:
      request: Requisicao atual em avaliacao.

    Retorno:
      `true` quando a requisicao representa navegacao de documento.

    Contexto de uso:
      A experiencia instalada depende de a abertura inicial funcionar mesmo em
      oscilacoes de rede, sem exibir erro bruto do navegador.
  */

  return request.mode === "navigate";
}

function isDashboardStaticRequest(requestUrl) {
  /*
    Responsabilidade:
      Detectar assets estaticos servidos pelo shell do dashboard.

    Parametros:
      requestUrl: URL ja parseada da requisicao atual.

    Retorno:
      `true` quando o caminho aponta para `/dashboard/static/`.

    Contexto de uso:
      CSS, JS e icones podem ser servidos rapidamente do cache sem comprometer
      o fluxo de navegacao principal do operador.
  */

  return requestUrl.pathname.startsWith("/dashboard/static/");
}

async function precacheDashboardShell() {
  /*
    Responsabilidade:
      Armazenar o conjunto minimo de telas e icones para o PWA.

    Parametros:
      Nenhum.

    Retorno:
      Promise concluida apos o preenchimento do cache estatico.

    Contexto de uso:
      Mantem a abertura inicial do app previsivel e garante fallback para a
      Home quando uma navegacao subsequente ficar sem conectividade.
  */

  const cache = await caches.open(DASHBOARD_PWA_STATIC_CACHE);
  await cache.addAll(DASHBOARD_PWA_PRECACHE_URLS);
}

async function cleanupObsoleteDashboardCaches() {
  /*
    Responsabilidade:
      Excluir caches antigos deixados por versoes anteriores do PWA.

    Parametros:
      Nenhum.

    Retorno:
      Promise concluida quando os caches obsoletos forem removidos.

    Contexto de uso:
      Reduz risco de misturar shell novo com responses antigas depois de um
      deploy e mantem o armazenamento do navegador sob controle.
  */

  const allowedCacheNames = new Set([
    DASHBOARD_PWA_STATIC_CACHE,
    DASHBOARD_PWA_RUNTIME_CACHE,
  ]);
  const cacheNames = await caches.keys();

  await Promise.all(
    cacheNames.map((cacheName) => {
      const belongsToDashboardPwa = cacheName.startsWith(DASHBOARD_PWA_CACHE_PREFIX);
      if (!belongsToDashboardPwa || allowedCacheNames.has(cacheName)) {
        return Promise.resolve();
      }
      return caches.delete(cacheName);
    }),
  );
}

async function respondToDashboardNavigation(request) {
  /*
    Responsabilidade:
      Priorizar rede para HTML e cair para cache quando necessario.

    Parametros:
      request: Requisicao de navegacao iniciada pelo navegador.

    Retorno:
      `Response` de rede, cache da rota ou fallback da Home do dashboard.

    Contexto de uso:
      Assim o operador recebe conteudo atual quando estiver online, mas ainda
      consegue abrir o app e continuar orientado em quedas momentaneas.
  */

  try {
    const networkResponse = await fetch(request);
    await storeSuccessfulResponse(DASHBOARD_PWA_RUNTIME_CACHE, request, networkResponse);
    return networkResponse;
  } catch (error) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    const offlineFallbackResponse = await caches.match(DASHBOARD_PWA_OFFLINE_FALLBACK_URL);
    if (offlineFallbackResponse) {
      return offlineFallbackResponse;
    }

    throw error;
  }
}

async function respondToDashboardStaticRequest(request, event) {
  /*
    Responsabilidade:
      Servir assets estaticos rapidamente e atualiza-los em segundo plano.

    Parametros:
      request: Requisicao de asset estatico dentro de `/dashboard/static/`.
      event: Evento `fetch` atual para prolongar a vida da atualizacao.

    Retorno:
      `Response` do cache ou da rede, conforme disponibilidade.

    Contexto de uso:
      Esta estrategia reduz tempo de abertura do shell instalado sem bloquear
      a atualizacao dos arquivos quando o navegador estiver online.
  */

  const cache = await caches.open(DASHBOARD_PWA_STATIC_CACHE);
  const cachedResponse = await cache.match(request);
  const networkResponsePromise = fetch(request)
    .then(async (networkResponse) => {
      await storeSuccessfulResponse(DASHBOARD_PWA_STATIC_CACHE, request, networkResponse);
      return networkResponse;
    })
    .catch(() => null);

  if (cachedResponse) {
    if (event && typeof event.waitUntil === "function") {
      event.waitUntil(networkResponsePromise);
    }
    return cachedResponse;
  }

  const networkResponse = await networkResponsePromise;
  if (networkResponse) {
    return networkResponse;
  }

  return Response.error();
}

async function respondToDashboardRuntimeRequest(request) {
  /*
    Responsabilidade:
      Tratar GETs nao estaticos com rede primeiro e cache como apoio.

    Parametros:
      request: Requisicao same-origin do dashboard fora da categoria HTML.

    Retorno:
      `Response` de rede quando possivel, com fallback para cache.

    Contexto de uso:
      Isso cobre manifesto, APIs GET futuras sob `/dashboard` e demais
      recursos do shell sem endurecer a politica para tudo da mesma forma.
  */

  try {
    const networkResponse = await fetch(request);
    await storeSuccessfulResponse(DASHBOARD_PWA_RUNTIME_CACHE, request, networkResponse);
    return networkResponse;
  } catch (error) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
      return cachedResponse;
    }

    throw error;
  }
}

async function storeSuccessfulResponse(cacheName, request, response) {
  /*
    Responsabilidade:
      Persistir em cache apenas respostas seguras para reuso futuro.

    Parametros:
      cacheName: Nome do cache de destino.
      request: Requisicao usada como chave de armazenamento.
      response: Resposta retornada pela rede.

    Retorno:
      Promise concluida apos gravar a resposta elegivel.

    Contexto de uso:
      Evita armazenar erros HTTP ou respostas nao reutilizaveis, o que poderia
      congelar falhas temporarias dentro do app instalado.
  */

  if (!isDashboardCacheableResponse(response)) {
    return;
  }

  const cache = await caches.open(cacheName);
  await cache.put(request, response.clone());
}

function isDashboardCacheableResponse(response) {
  /*
    Responsabilidade:
      Validar se uma resposta pode ser reaproveitada com seguranca.

    Parametros:
      response: Resposta recebida da rede.

    Retorno:
      `true` quando a resposta representa sucesso HTTP reutilizavel.

    Contexto de uso:
      O dashboard precisa de cache confiavel. Guardar erros 500 ou redirects
      inesperados degradaria a abertura do PWA e mascararia falhas reais.
  */

  return response instanceof Response && response.ok;
}
