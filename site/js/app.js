(function () {
"use strict";
var apps = [], videos = {}, dados = null;

// ---------- normalização (sem acento/caixa/pontuação) ----------
function norm(s) {
  return (s || "").toLowerCase()
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-z0-9\s+#]/g, " ").replace(/\s+/g, " ").trim();
}
function esc(s) { return s.replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c])); }
function hi(txt, termos) {
  txt = txt || ""; var out = esc(txt);
  if (!termos.length) return esc(txt);
  try {
    var rx = new RegExp("(" + termos.map(escRx).join("|") + ")", "gi");
    out = esc(txt).replace(rx, "<mark>$1</mark>");
  } catch (e) { out = esc(txt); }
  return out;
}
function escRx(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

function tempoFmt(s) {
  if (s == null) return "–:–";
  var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(ss).padStart(2, "0");
}
function mesFmt(data) {
  if (!data) return "";
  var m = ["jan","fev","mar","abr","mai","jun","jul","ago","set","out","nov","dez"];
  var y = data.slice(0, 4), mo = +data.slice(5, 7);
  return m[mo - 1] + "/" + y;
}

// ---------- campos/weight da busca ----------
var CAMPOS = [
  { w: 10, get: a => a.nome },
  { w: 5,  get: a => a.descricao_repo },
  { w: 4,  get: a => a.descricao_curta },
  { w: 3,  get: a => (a.tags || []).join(" ") + " " + (a.idioma || "") + " " + (a.licenca || "") },
  { w: 2,  get: a => [a.repo, (a.lojas || []).map(l => l.url), a.homepage].join(" ") },
  { w: 1,  get: a => (a.aparicoes || []).map(x => x.titulo).join(" ") }
];

function buscar(q) {
  var termos = norm(q).split(" ").filter(Boolean);
  if (!termos.length) return apps;
  var res = [];
  for (var i = 0; i < apps.length; i++) {
    var a = apps[i], score = 0, ok = true;
    var normed = CAMPOS.map(c => norm(c.get(a)));
    for (var t = 0; t < termos.length; t++) {
      var te = termos[t], achou = 0, s = 0;
      for (var c = 0; c < CAMPOS.length; c++) {
        if (normed[c].indexOf(te) >= 0) {
          achou++; s += CAMPOS[c].w;
          if (c === 0 && normed[c].indexOf(te) === 0) s += 3; // início do nome
        }
      }
      if (!achou) { ok = false; break; }
      score += s;
    }
    if (ok) res.push([score, a]);
  }
  return res.sort((x, y) => y[0] - x[0]).map(x => x[1]);
}

// ---------- render ----------
var grid = document.getElementById("grid");
function youtube_embed(videoId, tempo) {
  return "https://www.youtube-nocookie.com/embed/" + videoId +
    "?start=" + (tempo || 0) + "&autoplay=1&rel=0";
}

function cardHtml(a, termos) {
  var descPri = a.descricao_curta ? esc(a.descricao_curta) : "";
  var descSec = a.descricao_repo ? esc(a.descricao_repo) : "";
  var urlRepo = a.repo ? a.repo.replace(/^https?:\/\/(www\.)?/, "") : "";
  var tagsHtml = (a.tags || []).slice(0, 6).map(t =>
    '<span class="tag" data-tag="' + esc(t) + '">' + esc(t) + '</span>').join("");
  var meta = [];
  if (a.stars) meta.push("★ " + a.stars.toLocaleString("pt-BR"));
  if (a.idioma) meta.push(esc(a.idioma));
  if (a.licenca && a.licenca !== "NOASSERTION") meta.push(esc(a.licenca));
  if (a.open_source !== false && /open source/i.test((a.descricao_curta || ""))) meta.push("open source");

  var aps = (a.aparicoes || []).map(function (ap) {
    var v = videos[ap.videoId] || ap;
    return '<button class="vid-btn" data-vid="' + ap.videoId + '" data-tempo="' +
      (ap.tempo != null ? ap.tempo : 0) + '">' +
      '<img loading="lazy" alt="" src="https://i.ytimg.com/vi/' + ap.videoId + '/mqdefault.jpg">' +
      '<span class="vt">' + esc(v.titulo.slice(0, 60)) +
      '<small>' + (mesFmt(ap.data) || "") + " · " + tempoFmt(ap.tempo) + '</small></span></button>';
  }).join("");

  return '<article class="card">' +
    '<div class="titulo-linha"><h3>' + hi(a.nome, termos) + '</h3>' +
    (urlRepo ? '<a class="repo-link" target="_blank" rel="noopener" href="' + esc(a.repo) + '">' +
      esc(urlRepo.slice(0, 28)) + ' ↗</a>' : '') + '</div>' +
    (descPri ? '<p class="desc"><b>' + hi(descPri, termos) + '</b></p>' : '') +
    (descSec ? '<p class="desc">' + hi(descSec, termos) + '</p>' : '') +
    (tagsHtml ? '<div class="tags">' + tagsHtml + '</div>' : '') +
    (meta.length ? '<div class="meta">' + meta.join(" · ") + '</div>' : '') +
    '<div class="aparicoes">' + aps + '</div></article>';
}

// ---------- ordenação ----------
var ordCampo = "relev", ordDir = "desc";
function valorOrd(a) {
  if (ordCampo === "nome") return (a.nome || "").toLowerCase();
  if (ordCampo === "stars") return a.stars == null ? null : a.stars;
  if (ordCampo === "video") { var ap = (a.aparicoes || [])[0]; return (ap && ap.data) || null; }
  if (ordCampo === "repo") return a.git_atualizado || null;
  return null;
}
function aplicarOrdem(res) {
  if (ordCampo === "relev") return ordDir === "desc" ? res : res.slice().reverse();
  var pares = res.map(a => [valorOrd(a), a]).sort(function (A, B) {
    var va = A[0], vb = B[0];
    if (va == null && vb == null) return 0;
    if (va == null) return 1;      // sem dado → sempre por último
    if (vb == null) return -1;
    var c;
    if (typeof va === "string") c = va.localeCompare(vb, "pt-BR");
    else c = va - vb;
    return ordDir === "asc" ? c : -c;
  });
  return pares.map(p => p[1]);
}
function aplicarOrdemUI() {
  document.getElementById("ord-campo").value = ordCampo;
  document.getElementById("ord-dir").textContent = ordDir === "asc" ? "↑" : "↓";
}
function estadoURL(q) {
  var u = new URL(location.href);
  if (q) u.searchParams.set("q", q); else u.searchParams.delete("q");
  if (ordCampo !== "relev" || ordDir !== "desc") {
    u.searchParams.set("ord", ordCampo); u.searchParams.set("dir", ordDir);
  } else { u.searchParams.delete("ord"); u.searchParams.delete("dir"); }
  history.replaceState(null, "", u);
}

function render(q) {
  var res = aplicarOrdem(buscar(q));
  var termos = norm(q).split(" ").filter(Boolean);
  document.getElementById("contagem").textContent =
    res.length + " de " + apps.length + " apps" + (q ? " · busca: “" + q + "”" : "");
  document.getElementById("vazio").hidden = res.length > 0;
  grid.innerHTML = res.slice(0, 200).map(a => cardHtml(a, termos)).join("");
}

// ---------- chips: tags comuns de uma vez ----------
function renderChips() {
  var freq = {}, top;
  apps.forEach(a => (a.tags || []).forEach(t => freq[norm(t)] = (freq[norm(t)] || 0) + 1));
  var nomes = {};
  apps.forEach(a => (a.tags || []).forEach(t => { nomes[norm(t)] = nomes[norm(t)] || t; }));
  frequentes = Object.keys(freq).filter(k => k.length > 2).sort((x, y) => freq[x] - freq[y]).slice(0, 8);
  top = frequentes.map(k => nomes[k]);
  var el = document.getElementById("chips");
  el.innerHTML = ["open source"].concat(top).map(t => '<span class="chip">' + esc(t) + '</span>').join("");
  el.addEventListener("click", function (ev) {
    if (ev.target.classList.contains("chip")) {
      var inp = document.getElementById("q");
      inp.value = ev.target.textContent; inp.dispatchEvent(new Event("input"));
    }
  });
}
var frequentes = [];

// ---------- init ----------
fetch("data/apps.json", { cache: "no-store" })
  .then(r => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then(function (d) {
    dados = d;
    apps = d.apps || [];
    (d.videos || []).forEach(v => videos[v.videoId] = v);
    document.getElementById("sub").textContent =
      (d.canal && d.canal.nome || "VegaData") + " · " + apps.length +
      " apps citados em " + (d.videos ? d.videos.length : 0) + " vídeos";
    document.getElementById("rodape").innerHTML =
      "atualizado em " + (d.atualizado || "").slice(0, 10) + " · dados do canal " +
      '<a target="_blank" rel="noopener" href="' + (d.canal.url || "#") + '">' + esc(d.canal.nome || "VegaData") + '</a>' +
      " · só apps com link público no vídeo";
    renderChips();
    var input = document.getElementById("q");
    var u0 = new URL(location.href);
    var q0 = u0.searchParams.get("q") || "";
    ordCampo = u0.searchParams.get("ord") || "relev";
    ordDir = u0.searchParams.get("dir") === "asc" ? "asc" : "desc";
    aplicarOrdemUI();
    input.value = q0;
    render(q0);
    input.addEventListener("input", function () {
      var q = input.value.trim(); render(q); estadoURL(q);
    });

    document.getElementById("ord-campo").addEventListener("change", function () {
      ordCampo = this.value; aplicarOrdemUI(); render(input.value.trim()); estadoURL(input.value.trim());
    });
    document.getElementById("ord-dir").addEventListener("click", function () {
      ordDir = ordDir === "asc" ? "desc" : "asc"; aplicarOrdemUI();
      render(input.value.trim()); estadoURL(input.value.trim());
    });
  })
  .catch(function () { document.getElementById("erro").hidden = false; });

// clique: thumbnail do vídeo → player embutido no tempo certo
grid.addEventListener("click", function (ev) {
  var chip = ev.target.closest(".tag");
  if (chip) {
    var inp = document.getElementById("q");
    inp.value = chip.getAttribute("data-tag"); inp.dispatchEvent(new Event("input"));
    return;
  }
  var btn = ev.target.closest(".vid-btn");
  if (!btn) return;
  var card = btn.closest(".card");
  var player = card.querySelector(".player");
  var vid = btn.getAttribute("data-vid"), t = +btn.getAttribute("data-tempo");
  if (player && player.dataset.vid === vid && player.dataset.tempo == t) { player.remove(); return; }
  if (player) player.remove();
  var d = document.createElement("div");
  d.className = "player";
  d.dataset.vid = vid; d.dataset.tempo = t;
  d.innerHTML = '<iframe loading="lazy" src="' + youtube_embed(vid, t) +
    '" allow="autoplay; encrypted-media; fullscreen; picture-in-picture" allowfullscreen title="Vídeo"></iframe>';
  card.appendChild(d);
});
})();
