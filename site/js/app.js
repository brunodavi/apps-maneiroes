import {
  norm, esc, buscar, aplicarOrdem, cardHtml, obterTagsFrequentes,
  chipsHtml, youtubeEmbed
} from "./utils.js";

export function createApp({
  document: doc = document,
  window: win = window,
  fetchFn = (...args) => fetch(...args)
} = {}) {
  let apps = [];
  let videos = {};
  let ordCampo = "relev";
  let ordDir = "desc";

  const el = id => doc.getElementById(id);
  const grid = el("grid");

  function estadoURL(q) {
    const url = new URL(win.location.href);
    if (q) url.searchParams.set("q", q);
    else url.searchParams.delete("q");

    if (ordCampo !== "relev" || ordDir !== "desc") {
      url.searchParams.set("ord", ordCampo);
      url.searchParams.set("dir", ordDir);
    } else {
      url.searchParams.delete("ord");
      url.searchParams.delete("dir");
    }
    win.history.replaceState(null, "", url);
  }

  function aplicarOrdemUI() {
    el("ord-campo").value = ordCampo;
    el("ord-dir").textContent = ordDir === "asc" ? "↑" : "↓";
  }

  function aplicarCliqueTag(valor) {
    const input = el("q");
    input.value = norm(input.value.trim()) === norm(valor) ? "" : valor;
    input.dispatchEvent(new win.Event("input"));
  }

  function render(q) {
    const resultados = aplicarOrdem(buscar(apps, q), ordCampo, ordDir);
    const termos = norm(q).split(" ").filter(Boolean);

    el("contagem").textContent =
      resultados.length + " de " + apps.length + " apps" +
      (q ? " · busca: “" + q + "”" : "");
    el("vazio").hidden = resultados.length > 0;
    grid.innerHTML = resultados.slice(0, 200)
      .map(app => cardHtml(app, termos, videos)).join("");

    const consulta = norm(q);
    doc.querySelectorAll("#chips .chip").forEach(chip => {
      chip.classList.toggle("on", norm(chip.textContent) === consulta);
    });
  }

  function renderChips() {
    const tags = obterTagsFrequentes(apps);
    const container = el("chips");
    container.innerHTML = chipsHtml(tags);
    container.addEventListener("click", event => {
      const chip = event.target.closest(".chip");
      if (chip) aplicarCliqueTag(chip.textContent);
    });
  }

  function syncLimpa() {
    el("limpa").hidden = !el("q").value;
  }

  function configurarEventos() {
    const input = el("q");
    const limpa = el("limpa");

    limpa.addEventListener("click", () => {
      input.value = "";
      input.dispatchEvent(new win.Event("input"));
      input.focus();
    });

    input.addEventListener("input", () => {
      syncLimpa();
      const q = input.value.trim();
      render(q);
      estadoURL(q);
    });

    el("ord-campo").addEventListener("change", event => {
      ordCampo = event.currentTarget.value;
      aplicarOrdemUI();
      render(input.value.trim());
      estadoURL(input.value.trim());
    });

    el("ord-dir").addEventListener("click", () => {
      ordDir = ordDir === "asc" ? "desc" : "asc";
      aplicarOrdemUI();
      render(input.value.trim());
      estadoURL(input.value.trim());
    });

    grid.addEventListener("click", event => {
      const tag = event.target.closest(".tag");
      if (tag) {
        aplicarCliqueTag(tag.getAttribute("data-tag"));
        return;
      }

      const botao = event.target.closest(".vid-btn");
      if (!botao) return;

      const card = botao.closest(".card");
      const player = card.querySelector(".player");
      const videoId = botao.getAttribute("data-vid");
      const tempo = Number(botao.getAttribute("data-tempo") || 0);

      if (player && player.dataset.vid === videoId &&
          Number(player.dataset.tempo) === tempo) {
        player.remove();
        return;
      }
      if (player) player.remove();

      const container = doc.createElement("div");
      container.className = "player";
      container.dataset.vid = videoId;
      container.dataset.tempo = String(tempo);
      const iframe = doc.createElement("iframe");
      iframe.loading = "lazy";
      iframe.src = youtubeEmbed(videoId, tempo);
      iframe.allow = "autoplay; encrypted-media; fullscreen; picture-in-picture";
      iframe.allowFullscreen = true;
      iframe.title = "Vídeo";
      container.appendChild(iframe);
      card.appendChild(container);
    });
  }

  async function start() {
    const response = await fetchFn("data/apps.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`Falha ao carregar apps.json: HTTP ${response.status}`);
    const dados = await response.json();

    apps = dados.apps || [];
    videos = {};
    (dados.videos || []).forEach(video => { videos[video.videoId] = video; });

    el("sub").textContent =
      (dados.canal && dados.canal.nome || "VegaData") + " · " + apps.length +
      " apps citados em " + (dados.videos ? dados.videos.length : 0) + " vídeos";

    const canalNome = esc(dados.canal?.nome || "VegaData");
    const canalUrl = dados.canal?.url || "#";
    el("rodape").innerHTML =
      "atualizado em " + esc((dados.atualizado || "").slice(0, 10)) +
      " · dados do canal " +
      '<a target="_blank" rel="noopener noreferrer" href="' + esc(canalUrl) + '">' +
      canalNome + '</a> · só apps com link público no vídeo';

    renderChips();

    const urlInicial = new URL(win.location.href);
    const qInicial = urlInicial.searchParams.get("q") || "";
    ordCampo = urlInicial.searchParams.get("ord") || "relev";
    if (!["relev", "nome", "stars", "video", "repo"].includes(ordCampo)) ordCampo = "relev";
    ordDir = urlInicial.searchParams.get("dir") === "asc" ? "asc" : "desc";

    aplicarOrdemUI();
    el("q").value = qInicial;
    render(qInicial);
    syncLimpa();
    configurarEventos();

    return { apps, videos };
  }

  async function startWithErrorHandling() {
    try {
      return await start();
    } catch (error) {
      console.error(error);
      const erro = el("erro");
      if (erro) erro.hidden = false;
      return null;
    }
  }

  return { start, startWithErrorHandling };
}

// Inicializa automaticamente no navegador, mas não quando importado pelo Node.js.
if (typeof document !== "undefined" && typeof window !== "undefined") {
  const app = createApp();
  app.startWithErrorHandling();
}
