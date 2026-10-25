export function norm(s) {
  return (s || "").toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s+#]/g, " ").replace(/\s+/g, " ").trim();
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"
  })[c]);
}

function escRx(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export function hi(txt, termos = []) {
  txt = txt || "";
  if (!termos.length) return esc(txt);
  try {
    const rx = new RegExp("(" + termos.map(escRx).join("|") + ")", "gi");
    return esc(txt).replace(rx, "<mark>$1</mark>");
  } catch {
    return esc(txt);
  }
}

export function tempoFmt(s) {
  if (s == null || !Number.isFinite(Number(s))) return "–:–";
  s = Number(s);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = Math.floor(s % 60);
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(ss).padStart(2, "0");
}

export function mesFmt(data) {
  if (!data) return "";
  const meses = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  const ano = String(data).slice(0, 4);
  const mes = Number(String(data).slice(5, 7));
  return meses[mes - 1] ? `${meses[mes - 1]}/${ano}` : "";
}

export const CAMPOS = [
  { w: 10, get: a => a.nome },
  { w: 5, get: a => a.descricao_repo },
  { w: 4, get: a => a.descricao_curta },
  { w: 3, get: a => (a.tags || []).join(" ") + " " + (a.idioma || "") + " " + (a.licenca || "") },
  { w: 2, get: a => [a.repo, (a.lojas || []).map(l => l.url), a.homepage].join(" ") },
  { w: 1, get: a => (a.aparicoes || []).map(x => x.titulo).join(" ") }
];

export function buscar(apps, q, campos = CAMPOS) {
  const termos = norm(q).split(" ").filter(Boolean);
  if (!termos.length) return apps.slice();

  const resultados = [];
  for (const app of apps) {
    let score = 0;
    let ok = true;
    const normalizados = campos.map(c => norm(c.get(app)));

    for (const termo of termos) {
      let achou = false;
      let subtotal = 0;
      for (let i = 0; i < campos.length; i++) {
        const pos = normalizados[i].indexOf(termo);
        if (pos >= 0) {
          achou = true;
          subtotal += campos[i].w;
          if (i === 0 && pos === 0) subtotal += 3;
        }
      }
      if (!achou) {
        ok = false;
        break;
      }
      score += subtotal;
    }
    if (ok) resultados.push({ score, app });
  }

  return resultados
    .sort((a, b) => b.score - a.score)
    .map(item => item.app);
}

export function getAppLink(app) {
  const url = app.repo || (app.lojas || []).find(l => l && l.url)?.url || app.homepage || "";
  if (!url) return { url: "", label: "" };
  return {
    url,
    label: url.replace(/^https?:\/\/(www\.)?/, "").slice(0, 28)
  };
}

export function youtubeEmbed(videoId, tempo = 0) {
  return "https://www.youtube-nocookie.com/embed/" +
    encodeURIComponent(videoId) + "?start=" + (tempo || 0) + "&autoplay=1&rel=0";
}

export function cardHtml(app, termos = [], videos = {}) {
  const descPri = app.descricao_curta || "";
  const descSec = app.descricao_repo || "";
  const link = getAppLink(app);

  const tagsHtml = (app.tags || []).slice(0, 6).map(tag =>
    '<span class="tag" data-tag="' + esc(tag) + '">' + esc(tag) + '</span>'
  ).join("");

  const meta = [];
  if (app.stars) meta.push("★ " + Number(app.stars).toLocaleString("pt-BR"));
  if (app.idioma) meta.push(esc(app.idioma));
  if (app.licenca && app.licenca !== "NOASSERTION") meta.push(esc(app.licenca));
  if (app.open_source !== false && /open source/i.test(descPri)) meta.push("open source");
  if (app.sem_info) meta.push("sem fonte nem descrição");

  const aparicoes = (app.aparicoes || []).map(ap => {
    const video = videos[ap.videoId] || ap;
    const titulo = String(video.titulo || "Vídeo").slice(0, 60);
    const tempo = ap.tempo != null ? ap.tempo : 0;
    return '<button class="vid-btn" data-vid="' + esc(ap.videoId) + '" data-tempo="' + esc(tempo) + '">' +
      '<img loading="lazy" alt="" src="https://i.ytimg.com/vi/' + encodeURIComponent(ap.videoId) + '/mqdefault.jpg">' +
      '<span class="vt">' + esc(titulo) +
      '<small>' + esc(mesFmt(ap.data)) + " · " + esc(tempoFmt(ap.tempo)) + '</small></span></button>';
  }).join("");

  return '<article class="card">' +
    '<div class="titulo-linha"><h3>' + hi(app.nome, termos) + '</h3>' +
    (link.url ? '<a class="repo-link" target="_blank" rel="noopener noreferrer" href="' + esc(link.url) + '">' +
      esc(link.label) + ' ↗</a>' : '') + '</div>' +
    (descPri ? '<p class="desc"><b>' + hi(descPri, termos) + '</b></p>' : '') +
    (descSec ? '<p class="desc">' + hi(descSec, termos) + '</p>' : '') +
    (tagsHtml ? '<div class="tags">' + tagsHtml + '</div>' : '') +
    (meta.length ? '<div class="meta">' + meta.join(" · ") + '</div>' : '') +
    '<div class="aparicoes">' + aparicoes + '</div></article>';
}

export function valorOrd(app, campo) {
  if (campo === "nome") return (app.nome || "").toLowerCase();
  if (campo === "stars") return app.stars == null ? null : app.stars;
  if (campo === "video") {
    const ap = (app.aparicoes || [])[0];
    return (ap && ap.data) || null;
  }
  if (campo === "repo") return app.git_atualizado || null;
  return null;
}

export function aplicarOrdem(resultados, campo = "relev", direcao = "desc") {
  if (campo === "relev") return direcao === "desc" ? resultados.slice() : resultados.slice().reverse();

  return resultados.map(app => [valorOrd(app, campo), app])
    .sort(([a], [b]) => {
      if (a == null && b == null) return 0;
      if (a == null) return 1;
      if (b == null) return -1;
      const comparacao = typeof a === "string"
        ? a.localeCompare(b, "pt-BR")
        : a - b;
      return direcao === "asc" ? comparacao : -comparacao;
    })
    .map(([, app]) => app);
}

export function obterTagsFrequentes(apps, limite = 8) {
  const frequencias = {};
  const nomes = {};

  apps.forEach(app => (app.tags || []).forEach(tag => {
    const chave = norm(tag);
    frequencias[chave] = (frequencias[chave] || 0) + 1;
    nomes[chave] = nomes[chave] || tag;
  }));

  return Object.keys(frequencias)
    .filter(chave => chave.length > 2)
    .sort((a, b) => frequencias[a] - frequencias[b])
    .slice(0, limite)
    .map(chave => nomes[chave]);
}

export function chipsHtml(tags) {
  return ["open source", ...tags].map(tag =>
    '<span class="chip">' + esc(tag) + '</span>'
  ).join("");
}
