import test from "node:test";
import assert from "node:assert/strict";
import {
  norm, esc, tempoFmt, mesFmt, buscar, getAppLink, cardHtml,
  aplicarOrdem, obterTagsFrequentes, youtubeEmbed
} from "./utils.js";

test("norm remove acentos, pontuação e diferenças de caixa", () => {
  assert.equal(norm("ÁGIL!"), "agil");
});

test("esc protege caracteres HTML", () => {
  assert.equal(esc('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;");
});

test("tempoFmt formata minutos e horas", () => {
  assert.equal(tempoFmt(65), "1:05");
  assert.equal(tempoFmt(3661), "1:01:01");
  assert.equal(tempoFmt(null), "–:–");
});

test("mesFmt formata uma data válida", () => {
  assert.equal(mesFmt("2026-10-25"), "out/2026");
  assert.equal(mesFmt(""), "");
});

test("buscar encontra uma URL de loja mesmo sem repo", () => {
  const mixplorer = {
    nome: "MiXplorer",
    repo: null,
    lojas: [{ tipo: "loja", url: "https://www.mixplorer.com/" }]
  };
  assert.deepEqual(buscar([mixplorer], "mixplorer"), [mixplorer]);
  assert.deepEqual(buscar([mixplorer], "mixplorer.com"), [mixplorer]);
});

test("getAppLink prioriza repo, depois loja e depois homepage", () => {
  assert.equal(getAppLink({ repo: "https://github.com/a/b" }).url, "https://github.com/a/b");
  assert.equal(getAppLink({
    repo: null,
    lojas: [{ url: "https://www.mixplorer.com/" }]
  }).url, "https://www.mixplorer.com/");
  assert.equal(getAppLink({
    repo: null, lojas: [], homepage: "https://example.com"
  }).url, "https://example.com");
  assert.deepEqual(getAppLink({ repo: null, lojas: [] }), { url: "", label: "" });
});

test("cardHtml exibe link da loja quando repo é nulo", () => {
  const html = cardHtml({
    nome: "MiXplorer",
    repo: null,
    lojas: [{ url: "https://www.mixplorer.com/" }]
  });
  assert.match(html, /href="https:\/\/www\.mixplorer\.com\/"/);
  assert.match(html, /mixplorer\.com\//);
});

test("busca exige que todos os termos sejam encontrados", () => {
  const apps = [
    { nome: "MiXplorer", tags: ["android"] },
    { nome: "Amaze", tags: ["file manager"] }
  ];
  assert.deepEqual(buscar(apps, "mixplorer android"), [apps[0]]);
  assert.deepEqual(buscar(apps, "mixplorer inexistente"), []);
});

test("aplicarOrdem mantém itens sem dados no fim", () => {
  const apps = [
    { nome: "Sem estrelas", stars: null },
    { nome: "B", stars: 2 },
    { nome: "A", stars: 5 }
  ];
  assert.deepEqual(aplicarOrdem(apps, "stars", "desc"), [apps[2], apps[1], apps[0]]);
});

test("obterTagsFrequentes agrega tags normalizadas", () => {
  const apps = [
    { tags: ["Android", "open source"] },
    { tags: ["android", "File Manager"] }
  ];
  assert.deepEqual(obterTagsFrequentes(apps), ["open source", "File Manager", "Android"]);
});

test("youtubeEmbed constrói URL de incorporação", () => {
  assert.equal(
    youtubeEmbed("abc123", 42),
    "https://www.youtube-nocookie.com/embed/abc123?start=42&autoplay=1&rel=0"
  );
});
