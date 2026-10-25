# Apps Maneirões

Página de busca dos apps citados nos vídeos de aplicativos do canal
[VegaData](https://youtube.com/@vegadata) — sem chave de API, sem dependências.

## Como funciona

```
src/gerar.py ──gera──▶ site/data/*.json ──servido por──▶ site/ (GitHub Pages)
```

- **`src/gerar.py`** (Python puro, só stdlib): coleta os vídeos das quatro playlists da série
  + a aba de uploads do canal (endpoint público `youtubei/v1`, o mesmo que o yt-dlp usa),
  faz o parse das descrições (nome do app, links, qualificadores, "Tempos do vídeo"),
  deduplica apps entre vídeos e enriquece com descrição/tags/stars das APIs públicas
  de **GitHub/GitLab/Codeberg** ou da **página do F-Droid**.
- **`site/data/apps.json`** — dados prontos; **`site/index.html`** + `css/` + `js/` —
  busca client-side em JS vanilla (sem framework, sem build), thumbnails e player
  incorporado do YouTube abrindo no minuto certo
  (`youtube-nocookie.com/embed/...?start=<segundos>`).

```
site/              # página publicada no Pages
├── index.html
├── css/style.css
├── js/app.js
└── data/          # apps.json + caches (video-cache, repo-cache, excludes)
src/gerar.py       # gerador
test/test_gerar.py # testes (fixtures reais do YouTube)
```

## Developing localmente

```bash
python3 -m http.server 8000 -d site   # abre http://localhost:8000
```

> Abrir o `index.html` direto do disco (file://) não vai funcionar — `fetch`
> de arquivos locais é bloqueado pelo navegador. Use um servidor HTTP.

## Rodar a coleta

```bash
python3 src/gerar.py              # completa (reaproveita os caches)
python3 src/gerar.py --fresh      # descarta caches e coleta tudo de novo
python3 src/gerar.py --limit 8    # debug: só os N primeiros vídeos
python3 src/gerar.py --sem-repo   # pula o enriquecimento de repos
python3 src/gerar.py --video-id ssP04Cl1bmo        # adiciona um vídeo manualmente
python3 src/gerar.py --sem-info   # lista apps sem fonte nem descrição (sem rede, só lê)
python3 src/gerar.py --app-link "Kiwi Browser=https://github.com/kiwibrowser/src"
python3 test/test_gerar.py         # testes (fixtures reais do YouTube)
```

### Adicionar vídeo manualmente (`--video-id`)

Para vídeos que o radar automático pula (ex.: série antiga com título fora do
padrão). Refetcha o vídeo **ignorando o video-cache**, aceita 1+ app no parse e:
 continua o fluxo normal, incluindo o enriquecimento dos repos que ainda faltam:

```bash
python3 src/gerar.py --video-id <youtube-video-id> [outro-id ...]
```

O vídeo fica com `origem: "manual"` no `site/data/apps.json` e é removido do
`excludes.json` (memória negativa), para não ser descartado nas rodadas seguidas.

Caches (ficam em `site/data/` e podem/devem ser commitados — aceleram as rodadas
seguintes e permitem retomar de onde parou após um erro):

| arquivo | o quê |
|---|---|
| `site/data/excludes.json`     | vídeos comprovadamente fora da série (id + motivo + data) — rodadas seguintes nem consultam |
| `site/data/video-cache.json` | título/descrição/duração/data dos vídeos **da série** (regenera o parse sem rede) |
| `site/data/repo-cache.json`  | descrição/tags/stars de cada repo/f-droid (+ busca de repos por nome e páginas de loja, válidos 30 dias) |

A memória negativa (`excludes.json`) é preenchida automaticamente: vídeos fora
do padrão de título (skip definitivo) e vídeos com título de série mas sem apps
parseáveis na descrição (pendências — reavaliadas a cada rodada, sem refetch,
pois ficam no `video-cache.json`). Vídeos incluídos no catálogo são removidos
da memória negativa automaticamente. Você pode adicionar/excluir IDs
manualmente — exceto se o ID pertencer a uma playlist, que sempre vence.

**Fontes (playlists do canal):** Aplicativos Maneirões (mensal), Aplicativos
Open Source (antiga), Recomendações de apps (antiga) e Aplicativos para quem
tem acesso root. Fora delas, o gerador varre os uploads do canal inteiro
(750+ vídeos, pré-filtro por título) + buscas textuais.

## Apps sem fonte (aviso + resgate automático + listar)

Todo fim de rodada o gerador lista apps que ficaram **só com o nome** (sem repo
GitHub/GitLab/Codeberg, sem F-Droid e sem descrição). Antes do aviso ele tenta
se corrigir sozinho, em duas fontes:

1. **páginas de loja/site** — a Play Store não tem API de descrição, mas o HTML
   da página carrega `og:description` (com `hl=pt_BR` vem em português);
   idem apkmirror e sites do próprio app. Cacheado 30 dias.
2. **busca do GitHub pelo nome do app** (nome + `android`, por relevância, com
   filtro de similaridade — match fraco **não** é apontado, para não indicar
   repo errado). Positivo/negativo cacheados 30 dias (`busca@nome`).

O que sobrar (apps fechados tipo Snapseed/MiXplorer, ou projetos sem doc) fica
avisado e marcado no catálogo com `"sem_info": true` — o card no site mostra a
nota "sem fonte nem descrição". Para visualizar a lista completa a qualquer
hora, no catálogo atual, sem tocar em rede:

```
   aviso: 28 app(s) sem fonte nem descrição …

$ python3 src/gerar.py --sem-info
== 476 apps no catálogo; SEM informação (nem repo/f-droid, nem descrição): 28
   Tilla                 | (sem link)  | vídeos: ssP04Cl1bmo
   Kiwi Browser          | https://play.google.com/…  | vídeos: BfOeDIUwH8I
   …
```

### Corrigir à mão um app: `--app-link`

Quando você sabe onde está o dado do app (repo, GitLab, Codeberg, F-Droid,
Play Store, apkmirror ou site do app), passa o link e o gerador atualiza tudo
no ato (repo/loja anexada + descrição/tags/stars puxadas de imediato) e
**persiste a correção** em `repo-cache.json` (`manual@nome`) — as rodadas
seguintes e o CI reaplicam-na após o parse dos vídeos, automaticamente:

```
$ python3 src/gerar.py --app-link "Kiwi Browser=https://github.com/kiwibrowser/src"
   OK: Kiwi Browser ← https://github.com/kiwibrowser/src

$ python3 src/gerar.py --app-link "MDM@fPZKGseLI58=https://codeberg.org/dev/mdm"
   OK: MDM ← https://codeberg.org/dev/mdm
```

- `"App"` casa pelo nome (ignorando acento/caixa) **ou pelo id da Play
  (`com.empresa.app`) / `repo:owner/repo` / `fdroid:pkg`**
- nomes repetidos entre vídeos desambiguam com `@videoId` (pegue o id no
  `--sem-info` — coluna "vídeos")
- múltiplos `--app-link` no mesmo comando atualizam vários apps
- para desfazer uma correção, apague a entrada `manual@<nome>` do
  `repo-cache.json` (ou ajuste a URL lá) e rode de novo

## Publicar no GitHub Pages

1. Suba o repo no GitHub (pasta `apps-maneiroes`)
2. **Settings → Pages → Source: `GitHub Actions`** (a pasta inteira `site/` é
   publicada pelo workflow — por isso o caminho do site é `site/`, irrelevante
   para quem acessa: a raiz do Pages vira `index.html`)
3. O workflow `.github/workflows/atualizar-apps.yml` roda no dia 5 de cada mês
   (ou por "Run workflow" na aba Actions), regenera o `site/data/apps.json`,
   commita e **publica no Pages no mesmo run** (job `publicar`, que também
   dispara em `push` para `main`).

Nenhum segredo é necessário: o `GITHUB_TOKEN` padrão (injetado automaticamente
no Actions) aumenta o limite da API do GitHub de 60/h para 1000/h e habilita o
**GraphQL em lote** (até 100 repos por chamada).

### Secrets opcionais

| Secret | para quê | escopo mínimo |
|---|---|---|
| `GH_PAT` | rodar `src/gerar.py` local sem o limite anônimo de 60/h; GraphQL em lote na sua máquina | fine-grained · *Public repositories: read-only* |
| `YOUTUBE_API_KEY` | troca o scraping do YouTube pela Data API oficial: `videos.list` em lote (50 vídeos/chamada) e filtro `publishedAfter` na janela | API key restrita ao *YouTube Data API v3* (leitura) |

O gerador usa automaticamente se detectar (`GITHUB_TOKEN`/`GH_TOKEN`/`GH_PAT` e
`YOUTUBE_API_KEY`) e funciona sem nenhum deles — sem chave usa os endpoints
públicos do YouTube + fallback HTML para o GitHub.

## Regra de janela (economia no CI)

Sem `--janela` o gerador roda **sem limite de idade** (catálogo completo, ideal
em rodadas locais). O workflow do Actions usa **`--janela 3`** por decisão do
mantenedor: confirma vídeos de série novos dos últimos 3 meses (o que já está
nos caches anteriormente não é re-buscado nem perdido; o restante do catálogo é
sempre mantido). Com `YOUTUBE_API_KEY`, o filtro é aplicado na própria API
(`publishedAfter`). A janela é uma opção de economia, não de catalogação.

### Descoberta de vídeos (3 camadas, nunca perde catálogo)

1. **Playlists** da série (fonte de verdade, sempre completa)
2. **Abração de uploads** do canal **pré-filtrada por título** (`SERIES_RE`) —
   vídeos de servidor/htpc/aliexpress nem chegam a baixar descrição
3. **Busca textual no canal** (`apps maneirões`, `apps brabos`, `apps
   diferenciados`, `aplicativos open source`) via Innertube (sem chave) ou
   `search.list` com `YOUTUBE_API_KEY` — acha vídeos fora de playlist mesmo
   que venham com título diferente

Além disso, o `apps.json` anterior é sempre readicionado ao lote de candidatos:
catálogo é **cumulativo** — a janela só restringe descobertas novas.
(Não há tag/hashtag pública confiável nos vídeos do canal; a seleção da série
é pelo título + validação dos apps na descrição, que é onde os apps existem.)

### Ordenação na página

O seletor ao lado da busca ordena por **Relevância** (padrão), **Nome**,
**Estrelas**, **Data do vídeo** e **Atualização do repo** — com botão ↑/↓ para
crescente/descrecente. A escolha fica na URL (`?ord=stars&dir=asc`), então dá
para compartilhar uma ordenação pronta. O campo `git_atualizado` (último push)
é preenchido pelo GitHub/GitLab/Codeberg; no primeiro run do Actions (com
`GITHUB_TOKEN`) o GraphQL em lote preenche as entradas do cache que faltarem.

## Estrutura do apps.json

```jsonc
{
  "apps": [{
    "nome": "Twine",
    "descricao_curta": "Open source",              // qualificador do vídeo ("* Open source…")
    "descricao_repo": "A multiplatform RSS reader", // API do GitHub/GitLab/Codeberg/F-Droid
    "tags": ["android", "rss-reader"],              // topics do repo (ou categorias do F-Droid)
    "stars": 4200, "idioma": "Kotlin", "licenca": "MIT",
    "git_atualizado": "2026-08-14",                 // último push (GitHub/GitLab/Codeberg)
    "repo": "https://github.com/…",                 // nulo p/ apps só de loja
    "lojas": [{"tipo": "loja:fdroid", "url": "…"}],
    "aparicoes": [{"videoId": "5vhhPU0tBy4", "tempo": 30, "data": "2026-09-05", "titulo": "…"}]
  }],
  "videos": [{ "videoId": "…", "titulo": "…", "data": "…", "duracao": 1050,
               "playlists": ["PLfz2…"], "origem": "playlist|busca|manual" }]
}
```
