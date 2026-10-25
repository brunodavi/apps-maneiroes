#!/usr/bin/env python3
"""
Gera apps.json — catálogo de apps citados nos vídeos "Aplicativos Maneirões" do canal VegaData.

- 100% stdlib (urllib), SEM chave de API do YouTube
  (usa os endpoints públicos youtubei/v1, os mesmos que o yt-dlp usa)
- Enriquecimento: GitHub/GitLab/Codeberg API pública (descrição, tags, stars)
                 e F-Droid (fdroiddata metadata, descrição + categorias)
- Cache em repo-cache.json para não repetir requisições entre rodas.

Uso:
    python3 gerar.py              # roda completa (reaproveita video-cache.json / repo-cache.json)
    python3 gerar.py --fresh      # ignora caches e coleta tudo de novo
    python3 gerar.py --limit 8    #debug: só os N primeiros vídeos
    python3 gerar.py --sem-repo   # pula enriquecimento de rede (usa só cache)
    python3 gerar.py --force      # não aborta se o número de vídeos diminuir

Caches (permitem retomar de onde parou após erro/abort):
    video-cache.json  → vídeoId: {titulo, descricao, duracao, data} (ou {"erro": true})
    repo-cache.json   → dado de cada repo/f-droid consultado
"""

import difflib
import html as _html
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

DIR = os.path.dirname(os.path.abspath(__file__))

CHANNEL_ID = "UCd2FHKnQ3ymrNhdsV9J0VmA"
CHANNEL_NAME = "VegaData"
PLAYLISTS = [
    "PLfz2Tqtsq7B8TiFdg2rnAyM7vsj3pdhUo",  # Aplicativos Maneirões (mensal)
    "PLfz2Tqtsq7B8b_HSwBxJ1j1sY7V3OX6VG",  # Aplicativos Open Source (antiga)
    "PLfz2Tqtsq7B8xplHNlbagA_600lo69EgE",  # Recomendações de apps (antiga)
    "PLfz2Tqtsq7B8y4pgbTeOQEmHYVCXm96R4",  # Aplicativos para quem tem acesso root
]

# chave pública web do YouTube (não é chave dev, não precisa de conta)
IT_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

# vídeos de "série de apps" no canal: título precisa ter app/aplicativo + tema
SERIES_RE = re.compile(
    r"(apps?|aplicativos?).*(android|open source)"
    r"|aplicativos\s+open\s+source"
    r"|recomendações? de (apps?|aplicativos?|players|lojas)"
    r"|aplicativos?.*(shizuku|adb)",
    re.I)

# séries antigas sem blocos de links: os capítulos "00:40 - Nome" AJUDAM a nome
# dos apps (formato do "Recomendações de Apps/Applicativos #1 a #6", ~2021)
LEGACY_CAPITULOS_RE = re.compile(
    r"recomendações? de (apps?|aplicativos?|players|lojas)"
    r"|aplicativos para quem tem acesso root",
    re.I)

# termos buscados NO CANAL (camada de descoberta além das playlists/uploads)
BUSCA_QUERIES = ["apps maneirões", "apps brabos", "apps diferenciados",
                 "aplicativos open source", "recomendações de apps",
                 "aplicativos que utilizam shizuku", "aplicativos que precisam do adb"]

FORA_SERIE_MOTIVO = "fora da série de apps (título)"

TS_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*[-–—]\s*(.+?)\s*$")
URL_RE = re.compile(r"^\s*(https?://\S+)\s*$")

NON_APP_TS = {"introducao", "intro", "encerramento", "fim", "final", "outro",
              "conclusao", "outrasrecomendacoeseconclusao"}
NON_APP_BLOCK = {"tempos do video", "links", "downloads", "videos da serie"}

NAME_SUFFIX_RE = re.compile(
    r"\s+(no|na|em|via)\s+(github|gitlab|codeberg|f-droid|fdroid|play store|google play|play|releases?|site oficial)\s*$",
    re.I)
NAME_PREFIX_RE = re.compile(r"^\s*site oficial d[ao]\s+", re.I)


def base_name(nome):
    """Nomes antigos vêm como "XClipper no F-Droid" / "Site oficial do Lawnchair"."""
    n = nome.strip()
    n = NAME_PREFIX_RE.sub("", n)
    prev = None
    while n != prev:
        prev, n = n, NAME_SUFFIX_RE.sub("", n).strip()
    return n or nome.strip()

REPO_HOSTS = {"github.com", "gitlab.com", "codeberg.org", "sourceforge.net"}

CLIENTS = [
    # fallback do formato de resposta; alguns vídeos dão UNPLAYABLE no WEB mas
    # o videoDetails/microformat continua vindo
    {"clientName": "WEB", "clientVersion": "2.20260101.00.00"},
    {"clientName": "ANDROID", "clientVersion": "19.44.38", "androidSdkVersion": 30},
    {"clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER", "clientVersion": "2.0"},
]


# ---------------------------------------------------------------- cache

def load_json(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"   AVISO: {os.path.basename(path)} corrompido, recomeçando vazio")
    return {}


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


# dados (aplicação + caches) ficam em site/data/ — servidos pelo Pages
DATA_DIR = os.path.join(os.path.dirname(DIR), "site", "data")
VIDEO_CACHE_PATH = os.path.join(DATA_DIR, "video-cache.json")
REPO_CACHE_PATH = os.path.join(DATA_DIR, "repo-cache.json")
EXCLUDES_PATH = os.path.join(DATA_DIR, "excludes.json")

# ---------------------------------------------------------------- infra http

def http_get(url, headers=None, tries=3, timeout=30):
    h = {"User-Agent": "apps-maneiroes-bot/1.0 (pagina estatica de busca)"}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace"), dict(r.headers)
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def http_post_json(url, payload, tries=3, timeout=30, headers=None):
    body = json.dumps(payload).encode()
    h = {"User-Agent": "apps-maneiroes-bot/1.0", "Content-Type": "application/json"}
    if headers:
        h.update(headers)
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=h)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (i + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise last


def innertube(endpoint, payload, client):
    ctx = {"client": dict(client, hl="pt", gl="BR")}
    return http_post_json(
        f"https://www.youtube.com/youtubei/v1/{endpoint}?key={IT_KEY}&prettyPrint=false",
        {"context": ctx, **payload},
    )


def walk(o, key):
    if isinstance(o, dict):
        for k, v in o.items():
            if k == key:
                yield v
            yield from walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, key)


# ---------------------------------------------------------------- YouTube Data API v3 (opcional)

def gh_token():
    for var in ("GITHUB_TOKEN", "GH_TOKEN", "GH_PAT", "GITHUB_PAT"):
        v = os.environ.get(var)
        if v:
            return v.strip()
    return None


def iso8601_seconds(s):
    """PT4M13S → 253 (duração ISO8601 da Data API)."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", s or "")
    if not m:
        return None
    h, mi, se = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + se or None


def cutoff_date(meses):
    """--janela N → data ISO (Y-m-d) N meses atrás; None se sem janela."""
    if not meses or meses <= 0:
        return None
    d = datetime.now(timezone.utc) - timedelta(days=30 * int(meses))
    return d.strftime("%Y-%m-%d")


def api_get(endpoint, params, key):
    qs = urllib.parse.urlencode({**params, "key": key})
    body, _ = http_get(f"https://www.googleapis.com/youtube/v3/{endpoint}?{qs}")
    return json.loads(body)


def api_playlist_items(plid, cutoff=None, key=None, max_pages=10):
    """Vídeos de uma playlist (mais novos primeiro); para na data <= cutoff."""
    if cutoff is None:
        cutoff = cutoff_date(0)  # sem efeito
    out, page = [], None
    for _ in range(max_pages):
        p = {"part": "snippet,contentDetails", "playlistId": plid, "maxResults": 50}
        if page:
            p["pageToken"] = page
        if cutoff is not None:
            p |= {}
        d = api_get("playlistItems", p, key)
        for it in d.get("items", []):
            sn = it.get("snippet") or {}
            out.append({
                "videoId": (it.get("contentDetails") or {}).get("videoId"),
                "titulo": sn.get("title") or "",
                "data": (sn.get("publishedAt") or "")[:10] or None,
            })
        page = d.get("nextPageToken")
        last = out[-1]["data"] if out else None
        if (cutoff and last and last < cutoff) or (not page and not d.get("nextPageToken")):
            break
        time.sleep(0.1)
    if cutoff:
        out = [x for x in out if (x["data"] or "9999-99-99") >= cutoff]
    return [x for x in out if x["videoId"]]


def api_videos_info(vids, key):
    """videos.list em lotes de 50 → {videoId: info} (1 chamada por 50 vídeos)."""
    res = {}
    for i in range(0, len(vids), 50):
        d = api_get("videos", {
            "part": "snippet,contentDetails",
            "id": ",".join(vids[i:i + 50]),
        }, key)
        for it in d.get("items", []):
            sn = it.get("snippet") or {}
            res[it["id"]] = {
                "titulo": sn.get("title") or "",
                "descricao": sn.get("description") or "",
                "duracao": iso8601_seconds((it.get("contentDetails") or {}).get("duration")),
                "data": (sn.get("publishedAt") or "")[:10] or None,
            }
        time.sleep(0.1)
    return res


# ---------------------------------------------------------------- GitHub GraphQL (lote)

GH_GRAPHQL = "https://api.github.com/graphql"


def gql_necessario(ce):
    """GraphQL refresca: entries sem git_atualizado (parciais nistêmicas incluídas)."""
    return ce is None or ("erro" not in ce and not ce.get("git_atualizado"))


def lookup_graphql_github(apps, cache, tok):
    """Lotes de até 100 repos do GitHub em 1 chamada GraphQL; grava no cache."""
    itens = []
    for key, e in apps.items():
        if not e["repo"]:
            continue
        nurl, host = normalize_repo_url(e["repo"])
        if host == "github.com" and gql_necessario(cache.get("repo@" + nurl)):
            o, r = urllib.parse.urlparse(nurl).path.strip("/").split("/")[:2]
            itens.append((nurl, o, r))
    feitos = 0
    for i in range(0, len(itens), 100):
        sub = itens[i:i + 100]
        q = " ".join(
            f"r{j}: repository(owner: \"{o}\", name: \"{r}\") "
            "{ description stargazerCount pushedAt homepageUrl "
            "primaryLanguage { name } licenseInfo { spdxId } "
            "repositoryTopics(first: 12) { nodes { topic { name } } } }"
            for j, (_, o, r) in enumerate(sub))
        resp = http_post_json(
            GH_GRAPHQL, {"query": "query { " + q + " }"},
            headers={"Authorization": "Bearer " + tok}, timeout=90)
        if resp.get("errors") and not resp.get("data"):
            raise RuntimeError(resp["errors"][0].get("message", "?"))
        data = resp.get("data") or {}
        for j, (nurl, _, _) in enumerate(sub):
            d = data.get("r" + str(j))
            ckey = "repo@" + nurl
            if d is None:
                cache[ckey] = {"erro": 404}
                continue
            info = {
                "descricao_repo": (d.get("description") or "")[:400] or None,
                "tags": [t["topic"]["name"]
                         for t in (d.get("repositoryTopics") or {}).get("nodes", [])
                         if t and t.get("topic")][:12],
                "stars": d.get("stargazerCount"),
                "git_atualizado": (d.get("pushedAt") or "")[:10] or None,
                "idioma": (d.get("primaryLanguage") or {}).get("name"),
                "licenca": (d.get("licenseInfo") or {}).get("spdxId"),
                "homepage": d.get("homepageUrl") or None,
            }
            info["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            cache[ckey] = info
            feitos += 1
    return feitos


# ---------------------------------------------------------------- normalização

def norm(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9+#]", "", s.lower())


# ---------------------------------------------------------------- coleta YouTube

def get_playlist_videos(plid):
    vids, seen, cont = [], set(), None
    while True:
        payload = {"browseId": "VL" + plid}
        if cont:
            payload["continuation"] = cont
        data = innertube("browse", payload, CLIENTS[0])
        n0 = len(vids)
        for item in walk(data, "lockupViewModel"):
            vid = item.get("contentId")
            if not vid or vid in seen:
                continue
            title = ""
            try:
                title = item["metadata"]["lockupMetadataViewModel"]["title"]["content"]
            except Exception:
                runs = next(walk(item, "runs"), None)
                if runs:
                    title = runs[0].get("text", "")
            seen.add(vid)
            vids.append({"videoId": vid, "titulo": title})
        cont = None
        for cir in walk(data, "continuationItemRenderer"):
            tok = cir.get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
            if tok:
                cont = tok
                break
        if not cont or len(vids) == n0:
            break
        time.sleep(0.3)
    return vids


def get_channel_videos(max_pages=None):
    """Varredura completa da aba Vídeos (750+ uploads); max_pages limita só p/ teste."""
    vids, seen, cont, page = [], set(), None, 0
    params = "EgZ2aWRlb3PyBgQKAjoA"  # tab "Vídeos"
    while max_pages is None or page < max_pages:
        payload = {"browseId": CHANNEL_ID, "params": params}
        if cont:
            payload["continuation"] = cont
        data = innertube("browse", payload, CLIENTS[0])
        n0 = len(vids)
        for item in walk(data, "lockupViewModel"):
            vid = item.get("contentId")
            if not vid or vid in seen:
                continue
            title = ""
            try:
                title = item["metadata"]["lockupMetadataViewModel"]["title"]["content"]
            except Exception:
                pass
            seen.add(vid)
            vids.append({"videoId": vid, "titulo": title})
        cont = None
        for cir in walk(data, "continuationItemRenderer"):
            tok = cir.get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
            if tok:
                cont = tok
                break
        if not cont or len(vids) == n0:
            break
        page += 1
        time.sleep(0.3)
    return vids


def get_video_info(vid):
    """Título, descrição, duração, data de publicação (robusto a UNPLAYABLE)."""
    for client in CLIENTS:
        try:
            p = innertube("player", {"videoId": vid}, client)
        except Exception as e:
            time.sleep(1)
            continue
        d = p.get("videoDetails") or {}
        desc = d.get("shortDescription")
        if desc is None:
            time.sleep(0.3)
            continue
        mf = (p.get("microformat") or {}).get("playerMicroformatRenderer") or {}
        data = (mf.get("publishDate") or mf.get("uploadDate") or "")
        return {
            "titulo": d.get("title") or "",
            "descricao": desc,
            "duracao": int(d.get("lengthSeconds") or 0) or None,
            "data": (data or "")[:10] or None,
        }
    return None


# ---------------------------------------------------------------- parse da descrição

def classify_url(url):
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return None
    if (p.scheme or "").lower() not in ("http", "https"):
        return None
    host = p.netloc.lower().lstrip("www.")
    if not host:
        return None
    if "youtube.com" in host or "youtu.be" in host:
        return None
    if any(host == h or host.endswith("." + h) for h in REPO_HOSTS):
        return "repo"
    if "git.sr.ht" in host or "git.disroot.org" in host:
        return "repo"
    if "play.google.com" in host:
        return "loja:play"
    if "f-droid.org" in host:
        return "loja:fdroid"
    if "apkmirror.com" in host:
        return "loja:apkmirror"
    return "loja"


def parse_desc(desc):
    """Devolve (apps_locais, ts_map)."""
    apps, cur, tsmap = [], None, {}

    def flush():
        nonlocal cur
        if cur:
            nome = cur["nome"].rstrip(":").strip()
            if nome and (cur["urls"] or cur["qual"]) and norm(nome) not in NON_APP_BLOCK:
                apps.append({"nome": nome, "urls": cur["urls"], "qual": cur["qual"]})
        cur = None

    for raw in desc.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = TS_RE.match(line)
        if m:
            secs = int(m.group(1)) * 60 + int(m.group(2))
            if m.group(3) is not None:
                secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
            nname = norm(m.group(4))
            if nname and nname not in NON_APP_TS:
                tsmap.setdefault(nname, secs)
            flush()  # seção de timestamps encerra bloco anterior
            continue
        mu = URL_RE.match(line)
        if mu:
            url = mu.group(1)
            # só links de app/repo contam para o bloco (link de playlist/intro não)
            if cur is not None and classify_url(url) is not None:
                cur["urls"].append(url)
            continue
        if line.startswith("*"):
            if cur is not None:
                cur["qual"].append(line.lstrip("*").strip())
            continue
        if line.endswith(":"):
            flush()
            cur = {"nome": line[:-1].strip(), "urls": [], "qual": []}
        else:
            flush()
    flush()
    return apps, tsmap


def apps_por_capitulos(desc):
    """Formato antigo da série "Recomendações": capítulos '00:40 - Nome' SEM blocos
    de links. Cada capítulo vira um app citado (sem repo/loja; tempo vem do tsmap)."""
    apps = []
    vistos = set()
    for raw in desc.replace("\r", "").split("\n"):
        line = raw.strip()
        m = TS_RE.match(line)
        if not m:
            continue
        nome = m.group(4).strip().rstrip(":").strip()
        nn = norm(nome)
        if not nome or nn in NON_APP_TS or nn in vistos:
            continue
        vistos.add(nn)
        apps.append({"nome": nome, "urls": [], "qual": []})
    return apps


def match_tempo(app, tsmap):
    """Casa nome de app com nome no capítulo (norm exato, senão fuzzy)."""
    if not tsmap:
        return None
    n = norm(app["nome"])
    if n in tsmap:
        return tsmap[n]
    cand = difflib.get_close_matches(n, list(tsmap.keys()), n=1, cutoff=0.7)
    if cand and cand[0]:
        return tsmap[cand[0]]
    return None


# ---------------------------------------------------------------- dedup de apps

def app_key(nome, urls):
    for url in urls:
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        path = urllib.parse.urlparse(url).path.strip("/")
        if host in REPO_HOSTS:
            parts = path.split("/")
            if len(parts) >= 2:
                seg = parts[1]
                if seg.endswith(".git"):
                    seg = seg[:-4]
                return "repo:" + host + "/" + parts[0].lower() + "/" + seg.lower()
    for url in urls:
        if "play.google.com" in url:
            m = re.search(r"[?&]id=([\w.]+)", url)
            if m:
                return "play:" + m.group(1).lower()
        if "f-droid.org" in url:
            m = re.search(r"/packages/([\w.]+)", url)
            if m:
                return "fdroid:" + m.group(1).lower()
        host = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
        path = urllib.parse.urlparse(url).path.strip("/")
        if host and path:
            m = re.match(r"^(.+?)(?:\.git)?$", path)
            return "url:" + host + "/" + (m.group(1) if m else path).lower()
    return "nome:" + norm(nome)


# ---------------------------------------------------------------- excludes (memória negativa)

def em_playlist(vid, pl_map):
    return any(vid in pl_map.get(plid, []) for plid in PLAYLISTS)


def decidir_skip_excludes(vid, excludes, pl_map):
    """Exclude vence, EXCETO playlist (sempre vence) e pendências 'sem parse'
    (reavaliáveis: a regra de parse pode melhorar em rodada futura)."""
    if em_playlist(vid, pl_map):
        return False
    e = excludes.get(vid)
    if not e:
        return False
    return e.get("motivo") == FORA_SERIE_MOTIVO


def merge_excludes(excludes, pendencias, uploads_fora, pl_todos, hoje=None):
    """Mistura exclusões provadas; membros de playlist nunca entram.
    pendencias: [(videoId, motivo)]; uploads_fora: [{"videoId": …}]
    Devolve (novos, purga) — purga = ids a limpar do video-cache."""
    hoje = hoje or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    novos, purga = [], []
    for vid, motivo in pendencias:
        if vid in pl_todos or vid in excludes:
            continue
        excludes[vid] = {"motivo": motivo, "ts": hoje}
        novos.append(vid)
    for v in uploads_fora:
        vid = v["videoId"]
        if vid in pl_todos or vid in excludes:
            continue
        excludes[vid] = {"motivo": FORA_SERIE_MOTIVO, "ts": hoje}
        novos.append(vid)
        purga.append(vid)
    return novos, purga


def purgar_video_cache(vidcache, vids):
    """Remove ids do cache; devolve os que realmente existiam nele."""
    rem = [vid for vid in vids if vid in vidcache]
    for vid in rem:
        vidcache.pop(vid, None)
    return rem


# ---------------------------------------------------------------- enriquecimento

def load_cache():
    return load_json(REPO_CACHE_PATH)


def save_cache(cache):
    save_json(REPO_CACHE_PATH, cache)


def load_video_cache():
    return load_json(VIDEO_CACHE_PATH)


def save_video_cache(v):
    save_json(VIDEO_CACHE_PATH, v)


def load_excludes():
    return load_json(EXCLUDES_PATH)


def save_excludes(v):
    save_json(EXCLUDES_PATH, v)


def normalize_repo_url(url):
    p = urllib.parse.urlparse(url)
    host = p.netloc.lower().lstrip("www.")
    parts = [s for s in p.path.split("/") if s][:2]
    if len(parts) < 2:
        return None
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return f"https://{host}/{parts[0]}/{repo}", host


def gh_headers():
    h = {"Accept": "application/vnd.github+json"}
    tok = gh_token()
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def gh_html(url):
    """Fallback sem API: raspa a página pública do repo (title/og/language/stars)."""
    try:
        page, _ = http_get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"})
    except Exception:
        return None
    info = {"descricao_repo": None, "tags": [], "stars": None, "idioma": None,
            "licenca": None, "homepage": None, "parcial": True}
    m = re.search(r"<title>GitHub - ([^:]+):\s*(.*?)\s*·\s*GitHub</title>", page, re.S)
    if m and m.group(2):
        info["descricao_repo"] = html_unescape(m.group(2))[:400]
    else:
        m = re.search(r'<meta property="og:description" content="([^"]*)"', page)
        if m:
            d = html_unescape(m.group(1))
            info["descricao_repo"] = re.sub(r"\s*-\s*[\w.-]+/[\w.-]+$", "", d)[:400] or None
    m = re.search(r'repo-stars-counter-star"[^>]*title="([\d,\. ]+)"', page)
    if m:
        s = m.group(1).replace(",", "").replace(".", "").replace(" ", "")
        try:
            info["stars"] = int(s)
        except ValueError:
            pass
    m = re.search(r"language%3A([A-Za-z+#]+)", page)
    if m:
        info["idioma"] = m.group(1)
    return info


html_unescape = _html.unescape


def precisa_refetch_repo(ce):
    """REST: cache servível = tem data de repo, é parcial (HTML fallback) ou erro definitivo."""
    if ce is None:
        return True
    return not ("git_atualizado" in ce or ce.get("erro") or ce.get("parcial"))


def lookup_repo(url, cache, rate):
    normalizado, host = normalize_repo_url(url)
    if not normalizado:
        return None
    key = "repo@" + normalizado
    ce = cache.get(key)
    if not precisa_refetch_repo(ce):
        return ce
    info = {}
    try:
        if host == "github.com":
            u, r = urllib.parse.urlparse(normalizado).path.strip("/").split("/")[:2]
            try:
                body, hdr = http_get(f"https://api.github.com/repos/{u}/{r}", headers=gh_headers())
                if int(hdr.get("x-ratelimit-remaining", "999")) < 3:
                    rate["stop"] = True
                d = json.loads(body)
                info = {
                    "descricao_repo": (d.get("description") or "")[:400] or None,
                    "tags": (d.get("topics") or [])[:12],
                    "stars": d.get("stargazers_count"),
                    "git_atualizado": (d.get("pushed_at") or "")[:10] or None,
                    "idioma": d.get("language"),
                    "licenca": (d.get("license") or {}).get("spdx_id") or None,
                    "homepage": d.get("homepage") or None,
                }
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    info = {"erro": 404}
                else:
                    info = gh_html(normalizado) or {"erro": e.code}
        elif host == "gitlab.com":
            path = urllib.parse.quote(urllib.parse.urlparse(normalizado).path.strip("/"), safe="")
            body, _ = http_get(f"https://gitlab.com/api/v4/projects/{path}")
            d = json.loads(body)
            info = {
                "descricao_repo": (d.get("description") or "")[:400] or None,
                "tags": (d.get("topics") or d.get("tag_list") or [])[:12],
                "stars": d.get("star_count"),
                "git_atualizado": (d.get("last_activity_at") or "")[:10] or None,
                "idioma": None,
                "licenca": None,
                "homepage": None,
            }
        elif host == "codeberg.org":
            path = urllib.parse.urlparse(normalizado).path.strip("/")
            body, _ = http_get(f"https://codeberg.org/api/v1/repos/{path}")
            d = json.loads(body)
            info = {
                "descricao_repo": (d.get("description") or "")[:400] or None,
                "tags": (d.get("topics") or [])[:12],
                "stars": d.get("stars_count"),
                "git_atualizado": (d.get("updated") or "")[:10] or None,
                "idioma": None,
                "licenca": None,
                "homepage": d.get("website") or None,
            }
        else:
            return None
    except urllib.error.HTTPError as e:
        if e.code == 404:  # repo inexistente/renomeado → cacheia como definitivo
            cache[key] = {"erro": 404}
            return cache[key]
        info = {"erro": e.code}
    except Exception as e:
        info = {"erro": str(e)}
    if info.get("erro"):
        return None  # erro transitório (rate limit, rede): não cacheia, tenta de novo depois
    info["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache[key] = info
    return info


def lookup_fdroid(pkgid, cache):
    """Raspa a página pública do pacote no f-droid.org (summary/descrição/categoria)."""
    key = "fdroid@" + pkgid
    if key in cache:
        return cache[key]
    info = {}
    try:
        slug = pkgid.replace(".", ".")
        body, _ = http_get(
            f"https://f-droid.org/en/packages/{pkgid}/",
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
        )
        m = re.search(r'<div class="package-summary">\s*(.*?)\s*</div>', body, re.S)
        info["descricao_repo"] = html_unescape(m.group(1))[:400] if m else None
        if not info["descricao_repo"]:
            m = re.search(r'<div class="package-description"[^>]*>(.*?)</div>', body, re.S)
            if m:
                txt = re.sub(r"<br\s*/?>", "\n", m.group(1))
                txt = re.sub(r"<[^>]+>", "", txt)
                info["descricao_repo"] = html_unescape(txt).split("\n\n")[0].strip()[:400] or None
        mc = re.findall(r'href="https://f-droid\.org/apps/[^"]+">([^<]{2,40})</a>', body)
        ml = re.search(r"^License:\s*(\S+)", body, re.M)
        info["tags"] = [c.strip() for c in mc[:6]]
        info["licenca"] = ml.group(1) if ml else None
        info["stars"] = None
        info["idioma"] = None
        info["homepage"] = None
    except Exception as e:
        info = {"erro": str(e)}
    if info.get("erro"):
        return None
    info["ts"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cache[key] = info
    return info


def fdroid_pkgid(url):
    m = re.search(r"/packages/([\w.]+)", url)
    return m.group(1) if m else None


# ---------------------------------------------------------------- página da loja (última fonte)

def lookup_loja_page(url, cache):
    """Última fonte: a própria página da loja (Play Store, apkmirror, site).
    A Play Store não tem API de descrição, mas o HTML da página carrega
    og:description/meta description (com `hl=pt_BR` vem em português).
    Cacheia 30 dias (positivo/negativo); erro transitório não cacheia."""
    key = "loja@" + url
    ce = cache.get(key)
    if busca_servivel(ce):
        return ce
    try:
        body, _ = http_get(url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"})
        desc = None
        for pat in (
                r'<meta[^>]+(?:property="og:description"|name="description")[^>]+content="([^"]+)"',
                r'<meta[^>]+itemprop="description"[^>]+content="([^"]+)"'):
            m = re.search(pat, body)
            if m:
                cand = html_unescape(m.group(1)).strip()
                cand = re.sub(r"\s+", " ", cand)[:400]
                # lixo de loja: "Snapseed - Apps no Google Play" (title tupido no meta)
                if cand and " - Apps no Google Play" not in cand and " on Google Play" not in cand:
                    desc = cand
                    break
        info = {"descricao_repo": desc, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d")}
        if desc is None:
            info["erro"] = "sem descrição na página"
        cache[key] = info
        return info
    except Exception:
        return None


def tarefas_enriquecimento(apps):
    """Fila de enriquecimento, na ordem da melhor fonte p/ pior:
    repo citado no vídeo → F-Droid → página da loja (só quando o app ficou
    sem descrição alguma — evita requests de graça)."""
    tasks = []
    for e in apps.values():
        if e["repo"]:
            tasks.append(("repo", e))
            continue
        fd = next((fdroid_pkgid(l["url"]) for l in e["lojas"] if l["tipo"] == "loja:fdroid"), None)
        if fd:
            tasks.append(("fdroid", e, fd))
            continue
        if e["lojas"] and not (e["descricao_curta"] or e["descricao_repo"]):
            tasks.append(("loja", e, e["lojas"][0]["url"]))
    return tasks


# ---------------------------------------------------------------- apps sem fonte (validação + resgate)


def tem_fonte(e):
    """Fonte complementável = repo citado no vídeo ou F-Droid (dão descrição/tags automático)."""
    if e.get("repo"):
        return True
    return any((l or {}).get("tipo") == "loja:fdroid" for l in e.get("lojas", []))


def sem_info(e):
    """App sem NENHUM dado além do nome: sem repo/f-droid e sem descrição/tags.
    Link de Play Store sozinho não conta (a Play não expõe descrição via API)."""
    if tem_fonte(e):
        return False
    return not (e.get("descricao_curta") or e.get("descricao_repo") or e.get("tags"))


def escolher_repo(nome, resultados):
    """Escolhe, entre os achados da busca, o repo cujo nome casa com o app
    (norm igual ou razão ≥ 0.9). Empate: mais estrelas. Match fraco → None
    (melhor avisar 'sem fonte' do que apontar repo errado)."""
    n = norm(nome)
    if not n:
        return None
    cands = []
    for r in resultados:
        full = str(r.get("nome") or "")
        cand = norm(full.rsplit("/", 1)[-1])
        if not cand:
            continue
        if _repo_casa(n, cand):
            cands.append(r)
    if not cands:
        return None
    # exato vence (ex.: 'sdmaid' @1650★ deve ganhar de 'sdmaid-se' @7853★)
    return max(cands, key=lambda r: (norm(str(r.get("nome") or "").rsplit("/", 1)[-1]) == n,
                                     r.get("stars") or 0))


def _repo_casa(n, cand):
    """norm do app vs norm do nome do repo: igual, similar (razão ≥ .9) ou
    prefixo do outro com ≤ 6 chars extras ('LocalDream' ~ 'LocalDreamApp')."""
    if cand == n:
        return True
    if difflib.SequenceMatcher(None, n, cand).ratio() >= 0.9:
        return True
    return (cand.startswith(n) or n.startswith(cand)) and abs(len(cand) - len(n)) <= 6


def busca_servivel(ce):
    """Entrada do repo-cache da busca (positiva OU negativa) vale por 30 dias."""
    if not isinstance(ce, dict) or not ce.get("ts"):
        return False
    try:
        entao = datetime.strptime(ce["ts"], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc).date() - entao).days < 30


def lookup_busca_repo(nome, cache, rate):
    """App sem fonte → tenta achar o repo pela busca do GitHub (nome + android).
    Cacheia o resultado (positivo/negativo) em repo-cache.json (`busca@nome`)
    para não repetir a consulta nas rodadas seguintes. Devolve a URL ou None."""
    key = "busca@" + norm(nome)
    ce = cache.get(key)
    if busca_servivel(ce):
        return ce.get("repo_url")
    url = ("https://api.github.com/search/repositories?per_page=5&q="
           + urllib.parse.quote(f'"{nome}" android'))
    hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        body, hdr = http_get(url, headers=gh_headers())
        if int(hdr.get("x-ratelimit-remaining", "999")) < 2:
            rate["stop"] = True
        res = (json.loads(body).get("items") or [])
        melhor = escolher_repo(nome, [{"nome": it.get("full_name") or "",
                                       "stars": it.get("stargazers_count") or 0} for it in res])
        info = {"repo_url": f"https://github.com/{melhor['nome']}" if melhor else None,
                "ts": hoje}
        if melhor is None:
            info["erro"] = "sem match"  # negativo definitivo: 30 dias sem refazer
        cache[key] = info
        return info["repo_url"]
    except Exception:
        # transitório (rede/rate limit): NÃO cacheia — próxima rodada tenta de novo
        return None


# ---------------------------------------------------------------- link manual (--app-link)

APP_LINK_RE = re.compile(
    r"^\s*(?P<app>[^@=\n]+?)(?:@(?P<vid>[A-Za-z0-9_-]{6,}))?\s*=\s*(?P<url>\S+)\s*$")


def parse_app_link(spec):
    """--app-link "App[@videoId]=URL" → {app, video, url}; None se malformado."""
    m = APP_LINK_RE.match(spec or "")
    if not m:
        return None
    return {"app": m.group("app").strip(), "video": m.group("vid"), "url": m.group("url")}


def _chaves_app(e):
    chaves = {"nome:" + norm(e.get("nome") or "")}
    for l in e.get("lojas", []):
        m = re.search(r"[?&]id=([\w.]+)", l["url"]) if l["tipo"] == "loja:play" \
            else re.search(r"/packages/([\w.]+)", l["url"]) if l["tipo"] == "loja:fdroid" \
            else None
        if m:
            chaves.add(("play:" if l["tipo"] == "loja:play" else "fdroid:") + m.group(1).lower())
    if e.get("repo"):
        k = app_key(e["nome"], [e["repo"]])
        if k.startswith("repo:"):
            chaves.add(k)
            chaves.add("repo:" + k.split("/", 1)[1])  # forma sem host (repo:owner/repo)
    return chaves


def procurar_app(apps_list, alvo, video=None):
    """Casa o app p/ --app-link: nome (sem acento/caixa) ou ID (repo:<o>/<r>,
    play:<pacote>, fdroid:<pacote>, ou o pacote da Play sozinho).
    `video` (videoId de uma aparição) desambigua nomes repetidos.
    Devolve (app | None, candidatos | []): lista ≠ vazia = ambíguo."""
    alvo = (alvo or "").strip()
    if not alvo:
        return None, []
    com_prefixo = re.match(r"^(repo|url|nome|play|fdroid):(.+)$", alvo.lower())
    hits = []
    for e in apps_list:
        chaves = _chaves_app(e)
        if com_prefixo:
            matched = alvo.lower() in chaves
        else:
            matched = norm(alvo) == norm(e.get("nome") or "") or alvo.lower() in {
                c.split(":", 1)[1] for c in chaves if c.startswith(("play:", "fdroid:"))}
        if matched:
            hits.append(e)
    if video:
        hits = [h for h in hits
                if any(ap.get("videoId") == video for ap in h.get("aparicoes", []))]
    if len(hits) == 1:
        return hits[0], []
    if len(hits) > 1:
        return None, hits
    return None, []


def _id_loja(url):
    """Chave estável de loja: pacote da Play, pkgid do F-Droid, slug, ou a URL —
    dedupe de lojas ignora '?hl=' e afins."""
    if "play.google.com" in url:
        m = re.search(r"[?&]id=([\w.]+)", url)
        return m.group(1).lower() if m else url
    m = re.search(r"/packages/([\w.]+)", url)
    if m:
        return m.group(1).lower()
    return url.split("?")[0].rstrip("/")


def anexar_link(entry, url):
    """Anexa a URL ao app SEM rede: repo (normalizado, marca 'manual') ou loja.
    False se a URL não classificou ou já estava lá."""
    tipo = classify_url(url)
    if tipo == "repo":
        norm_url, _ = normalize_repo_url(url)
        if norm_url:
            entry["repo"], entry["origem_repo"] = norm_url, "manual"
            return True
        return False
    if tipo and tipo.startswith("loja"):
        k = (tipo, _id_loja(url))
        if k not in {(x["tipo"], _id_loja(x["url"])) for x in entry["lojas"]}:
            entry["lojas"].append({"tipo": tipo, "url": url})
            return True
    return False


def gravar_link_manual(cache, nome, url):
    """Persiste a correção no repo-cache (`manual@<nome>`) — rodadas futuras
    (e o CI) reaplicam-na depois do parse dos vídeos."""
    key = "manual@" + norm(nome)
    urls = (cache.get(key) or {}).get("urls") or []
    if url not in urls:
        urls.append(url)
    cache[key] = {"urls": urls, "ts": datetime.now(timezone.utc).strftime("%Y-%m-%d")}


def aplicar_manuais_cache(apps, cache):
    """Roda completa: reaplica manual@<nome> no catálogo recém-parseado.
    Substitui repo/video-anexos onde o usuário corrigiu manualmente.
    Devolve [(nome, url)] aplicadas."""
    aplicadas = []
    for key, val in cache.items():
        if not key.startswith("manual@"):
            continue
        nome_n = key[len("manual@"):]
        e = next((x for x in apps.values() if norm(x["nome"]) == nome_n), None)
        if e is None:
            continue
        for url in (val or {}).get("urls", []):
            if anexar_link(e, url):
                aplicadas.append((e["nome"], url))
    return aplicadas


def aplicar_info(e, info, idioma=True):
    """Merge de enriquecimento (repo REST/GraphQL/f-droid/loja) na entrada."""
    if "descricao_repo" in info:
        e["descricao_repo"] = info.get("descricao_repo") or e["descricao_repo"]
    e["tags"] = info.get("tags") or e["tags"]
    e["stars"] = info.get("stars") or e["stars"]
    e["git_atualizado"] = info.get("git_atualizado") or e["git_atualizado"]
    e["licenca"] = info.get("licenca") or e["licenca"]
    e["homepage"] = info.get("homepage") or e["homepage"]
    if idioma:
        e["idioma"] = info.get("idioma") or e["idioma"]


# ---------------------------------------------------------------- busca no canal (camada de descoberta)

def innertube_search_channel(q):
    """Busca textual restrita ao canal: innertube 'search' (sem chave)."""
    acervo, seen = [], set()
    # 1 página basta: cobre os vídeos de série recentes do canal
    payload = {"query": f"{CHANNEL_NAME} {q}".strip()}
    data = innertube("search", payload, CLIENTS[0])
    for item in walk(data, "videoRenderer"):
        vid = item.get("videoId")
        if not vid or vid in seen:
            continue
        owner = ""
        try:
            owner = item["ownerText"]["runs"][0]["text"]
        except Exception:
            pass
        titulo = (item.get("title") or {}).get("runs", [{}])[0].get("text", "")
        if owner and CHANNEL_NAME.lower() in owner.lower():
            seen.add(vid)
            acervo.append({"videoId": vid, "titulo": titulo})
    time.sleep(0.3)
    return acervo


def api_search_channel(q, cutoff, key):
    """Data API: search.list com channelId (nombré 1, q, type=video)."""
    p = {"part": "snippet", "channelId": CHANNEL_ID, "q": q,
         "type": "video", "maxResults": 50, "order": "date"}
    if cutoff:
        p["publishedAfter"] = cutoff + "T00:00:00Z"
    d = api_get("search", p, key)
    return [{"videoId": it["id"]["videoId"], "titulo": (it.get("snippet") or {}).get("title", "")}
            for it in d.get("items", []) if id_elem_ok(it)]


def id_elem_ok(it):
    return it.get("id") and it["id"].get("videoId") and (it.get("snippet") or {}).get("channelId") == CHANNEL_ID


# ---------------------------------------------------------------- principal

def main():
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    sem_repo = "--sem-repo" in args
    force = "--force" in args
    janela = int(args[args.index("--janela") + 1]) if "--janela" in args else 0
    data_limite = cutoff_date(janela)
    yt_key = os.environ.get("YOUTUBE_API_KEY")
    # --video-id <ID> [mais IDs...]: adiciona manualmente, refetchando SEM cache
    manual_ids = [args[i + 1].strip() for i, a in enumerate(args)
                  if a == "--video-id" and i + 1 < len(args) and args[i + 1].strip()]
    if manual_ids:
        print(f"== Modo manual: {len(manual_ids)} vídeo(s) via --video-id")
        limit = None  # não truncar candidatos com o alvo manual incluído

    # --sem-info: só LISTA os apps sem informação do catálogo atual e sai
    # (antes de qualquer rede — para checar o que falta / planejar correção)
    if "--sem-info" in args:
        d = load_json(os.path.join(DATA_DIR, "apps.json"))
        lista = [a for a in d.get("apps", []) if sem_info(a)]
        print(f"== {len(d.get('apps', []))} apps no catálogo; SEM informação (nem "
              f"repo/f-droid, nem descrição): {len(lista)}")
        for a in lista:
            fonte = next((l["url"] for l in a.get("lojas", []) if l), None)
            vids = ",".join(ap["videoId"] for ap in a.get("aparicoes", [])[:2])
            print(f"   {a['nome']:32s} | {fonte or '(sem link)':70s} | vídeos: {vids}")
        sys.exit(0)

    # --app-link "App[@videoId]=URL": corrige/atualiza UM app do catálogo e sai.
    # A URL (github/codeberg/playstore/fdroid/apkmirror/site) anexa repo/loja
    # e já puxa meta-dados (desc/tags/stars). Persiste em repo-cache.json
    # (`manual@nome`) para as rodadas futuras — e o CI — reaplicarem.
    links_spec = [args[i + 1].strip() for i, a in enumerate(args)
                  if a == "--app-link" and i + 1 < len(args) and args[i + 1].strip()]
    if links_spec:
        apps_path = os.path.join(DATA_DIR, "apps.json")
        d = load_json(apps_path)
        if not d.get("apps"):
            print("ERRO: apps.json vazio/inexistente — rode o gerador completo primeiro")
            sys.exit(1)
        cache = load_cache()
        rate = {"stop": False}
        ok = erros = 0
        for spec in links_spec:
            p = parse_app_link(spec)
            if not p:
                print(f"   ERRO: formato de '{spec}' (use \"App[@videoId]=URL\")")
                erros += 1
                continue
            e, amb = procurar_app(d["apps"], p["app"], p["video"])
            if e is None:
                if amb:
                    print(f"   ERRO: '{p['app']}' casa {len(amb)} apps — desambigue com @videoId:")
                    for h in amb[:5]:
                        vids = ",".join(ap["videoId"] for ap in h.get("aparicoes", [])[:4])
                        print(f"      · {h['nome']}  (vídeos: {vids}…)")
                else:
                    msg = f"   ERRO: '{p['app']}' não encontrado no catálogo"
                    if p["video"]:
                        msg += f" com @videoId '{p['video']}' (nenhuma aparição casa)"
                    print(msg)
                erros += 1
                continue
            if not anexar_link(e, p["url"]):
                print(f"   ({e['nome']}: URL já presente ou não utilizável: {p['url']})")
                erros += 1
                continue
            gravar_link_manual(cache, e["nome"], p["url"])
            tipo = classify_url(p["url"])
            # meta-dados na hora (rede só do app corrigido)
            if tipo == "repo":
                info = normalize_repo_url(p["url"]) and lookup_repo(
                    normalize_repo_url(p["url"])[0], cache, rate)
                if info and isinstance(info, dict) and "erro" not in info:
                    aplicar_info(e, info)
            elif tipo == "loja:fdroid" and fdroid_pkgid(p["url"]):
                info = lookup_fdroid(fdroid_pkgid(p["url"]), cache)
                if info and isinstance(info, dict) and "erro" not in info:
                    aplicar_info(e, info, idioma=False)
            elif tipo and tipo.startswith("loja") \
                    and not (e["descricao_curta"] or e["descricao_repo"]):
                info = lookup_loja_page(p["url"], cache) or {}
                if info.get("descricao_repo"):
                    aplicar_info(e, info, idioma=False)
            sem = sem_info(e)
            e.pop("sem_info", None)
            if sem:
                e["sem_info"] = True
            ok += 1
            extra = f" ({e['repo']})" if e["repo"] else ""
            print(f"   OK: {e['nome']} ← {p['url']}{extra}")
        # grava apps.json no MESMO formato do gerador (indent=1, sem sort direto)
        with open(apps_path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        save_cache(cache)
        print(f"\n--app-link: {ok} app(s) atualizado(s), {erros} problema(s)")
        sys.exit(0)

    # 1) playlists + canal -----------------------------------------------
    print("== Coletando playlists...")
    in_playlists, pl_map, seen_pl = [], {}, set()
    for plid in PLAYLISTS:
        if yt_key:
            vids = [{"videoId": x["videoId"], "titulo": x["titulo"]} for x in api_playlist_items(plid, key=yt_key)]
        else:
            vids = get_playlist_videos(plid)
        pl_map[plid] = [v["videoId"] for v in vids]
        for v in vids:
            if v["videoId"] not in seen_pl:
                seen_pl.add(v["videoId"])
                in_playlists.append(v)
        print(f"   {plid[-8:]}: {len(vids)} vídeos")
    print(f"   total playlist: {len(in_playlists)} vídeos únicos")

    print("== Coletando uploads do canal...")
    if manual_ids:
        # modo manual: pula varredura de uploads/buscas (catálogo anterior reconstrói o resto)
        uploads = []
        print("   (pulada: modo --video-id)")
    elif yt_key:
        uploads = api_playlist_items("UU" + CHANNEL_ID[2:], cutoff=data_limite, key=yt_key)
        uploads = [{"videoId": v["videoId"], "titulo": v["titulo"]} for v in uploads]
        if janela:
            print(f"   janela: only publicados depois de {data_limite} (YOUTUBE_API_KEY)")
    else:
        uploads = get_channel_videos()
    print(f"   {len(uploads)} uploads recentes")

    # pré-filtro por título ANTES de qualquer fetch de descrição:
    # vídeos de servidor/htpc/aliexpress etc. nunca chegam no player
    pl_todos = set()
    for plid in PLAYLISTS:
        pl_todos.update(pl_map.get(plid, []))
    uploads_titulo = [v for v in uploads if SERIES_RE.search(v["titulo"] or "")]
    uploads_fora = [v for v in uploads
                    if not SERIES_RE.search(v["titulo"] or "") and v["videoId"] not in pl_todos]
    print(f"   {len(uploads_titulo)} com título da série de apps (pré-filtro)")

    print("== Buscando no canal (camada de descoberta)...")
    achados_busca = []
    for q in ([] if manual_ids else BUSCA_QUERIES):
        r = api_search_channel(q, data_limite, yt_key) if yt_key else innertube_search_channel(q)
        achados_busca += r
        print(f"   “{q}”: {len(r)} vídeo(s) do canal")

    # catálogo anterior entra sempre: regeneração é cumulativa
    prev_videos, prev_ids_origem = [], {}
    if "--fresh" not in args:
        prev = load_json(os.path.join(DATA_DIR, "apps.json"))
        if isinstance(prev, dict):
            for w in (prev.get("videos") or []):
                prev_videos.append({"videoId": w["videoId"], "titulo": w["titulo"]})
                if w.get("origem") in ("busca", "manual"):
                    prev_ids_origem[w["videoId"]] = w.get("origem")
    prev_busca_ids = {vid for vid, o in prev_ids_origem.items() if o == "busca"}
    prev_auto_ids = set(prev_ids_origem)  # busca OU manual: isento de excludes/janela

    candidatos, seen = [], set()
    extra = [{"videoId": vid, "titulo": ""} for vid in manual_ids]
    for v in in_playlists + uploads_titulo + achados_busca + prev_videos + extra:
        if v["videoId"] not in seen:
            seen.add(v["videoId"])
            candidatos.append(v)
    if limit is not None:
        candidatos = candidatos[:limit]
    print(f"   {len(candidatos)} candidatos a processar")

    # 2) player + parse + inclusão ---------------------------------------
    print("== Processando vídeos...")
    fresh = "--fresh" in args
    vidcache = {} if fresh else load_video_cache()
    excludes = {} if fresh else load_excludes()
    excludes_pend, purga_cache = [], []
    excludes_dirty = False
    videos_out, apps, by_base = [], {}, {}
    pulados_velhos = 0
    pulado_por_exclude = 0
    if yt_key:
        faltando = [v["videoId"] for v in candidatos if v["videoId"] not in vidcache]
        if faltando:
            print(f"   (YOUTUBE_API_KEY) videos.list em lote: {len(faltando)} vídeo(s)")
            infos_lote = api_videos_info(faltando, yt_key)
            for vid, info in infos_lote.items():
                vidcache[vid] = info
            save_video_cache(vidcache)
    manual_set = set(manual_ids)
    for i, v in enumerate(candidatos):
        vid = v["videoId"]
        in_pl = em_playlist(vid, pl_map)
        if vid in excludes and (vid in manual_set or vid in prev_auto_ids):
            # vídeo já catalogado (anterior/manual) não pode morrer na memória negativa
            excludes.pop(vid)
            excludes_dirty = True
        if vid in manual_set:
            # SEM cache: busca sempre do zero e atualiza a entrada existente
            info = get_video_info(vid)
            if info:
                vidcache[vid] = info
                save_video_cache(vidcache)
            else:
                print(f"   --video-id {vid}: sem dados do player — nada adicionado")
                continue
        elif vid in prev_auto_ids and vid not in vidcache:
            # catálogo anterior que perdeu a entrada do cache: refetch normal
            info = get_video_info(vid)
            if info:
                vidcache[vid] = info
                save_video_cache(vidcache)
        elif decidir_skip_excludes(vid, excludes, pl_map):
            pulado_por_exclude += 1
            purga_cache.append(vid)
            continue
        elif vid in vidcache:
            info = vidcache[vid]
            if info.get("erro"):
                print(f"   pulando {vid} (falha permanente em rodada anterior, use --fresh)")
                continue
        else:
            info = get_video_info(vid)
            if info:
                vidcache[vid] = info
                save_video_cache(vidcache)  # salvo vídeo a vídeo: dá resume
            else:
                vidcache[vid] = {"erro": True}
                save_video_cache(vidcache)
                print(f"   AVISO: sem dados para {vid} ({v['titulo'][:40]})")
                continue
        apps_local, tsmap = parse_desc(info["descricao"] or "")
        # fallback: séries antigas sem links de apps (capítulos = nomes de apps)
        if not apps_local and LEGACY_CAPITULOS_RE.search(info["titulo"] or ""):
            apps_local = apps_por_capitulos(info["descricao"] or "")
            if apps_local:
                print(f"   formato antigo ({vid}): {len(apps_local)} app(s) pelos capítulos")
        if vid in manual_set:
            if not apps_local:
                print(f"   --video-id {vid}: nenhum app parseado — nada adicionado")
                continue
            origem = "manual"
            print(f"   + MANUAL: {vid} | {info['titulo'][:60]} | {len(apps_local)} app(s)")
        elif in_pl:
            origem = "playlist"
        else:
            if not (SERIES_RE.search(info["titulo"]) and len(apps_local) >= 2):
                # título de série mas descrição não rendeu apps: não exclui a
                # duração (a regra de parse pode melhorar) e fica no video-cache
                if not info.get("erro"):
                    excludes_pend.append((vid, "título de série sem parse de apps"))
                continue  # vídeo avulso do canal, não é da série
            # regra de janela: vídeos fora de playlist mais antigos que N meses
            # ficam fora, EXCETO os já catalogados ou adicionados manualmente
            if (data_limite and vid not in prev_busca_ids and vid not in manual_set
                    and (info.get("data") or "") and info["data"] < data_limite):
                pulados_velhos += 1
                continue
            origem = "busca"
            print(f"   + FORA DA PLAYLIST: {vid} | {info['titulo'][:60]}")

        playlists_v = [pl for pl in PLAYLISTS if vid in pl_map[pl]]
        videos_out.append({
            "videoId": vid,
            "titulo": info["titulo"],
            "url": f"https://youtu.be/{vid}",
            "data": info["data"],
            "duracao": info["duracao"],
            "playlists": playlists_v,
            "origem": origem,
            "n_apps": len(apps_local),
        })
        if excludes.pop(vid, None):
            excludes_dirty = True

        vinfo = {
            "videoId": vid,
            "titulo": info["titulo"],
            "data": info["data"],
            "thumbnail": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        }
        for a in apps_local:
            repos = [u for u in a["urls"] if classify_url(u) == "repo"]
            lojas = [u for u in a["urls"] if (classify_url(u) or "").startswith("loja")]
            base = base_name(a["nome"])
            nbase = norm(base)
            # chave: repo quando existe; senão nome-base (une "no GitHub"/"no F-Droid"/"na Play Store")
            key = app_key(base, a["urls"]) if repos else ("nome:" + nbase)
            entry = apps.get(key)
            if entry is None and nbase in by_base:
                entry = by_base[nbase]  # ex.: "OpenBoard no GitHub" vindo antes de "...na Play Store"
            if entry is None:
                entry = {
                    "nome": base,
                    "descricao_curta": " ".join(a["qual"]) or None,
                    "descricao_repo": None,
                    "tags": [],
                    "stars": None,
                    "git_atualizado": None,
                    "idioma": None,
                    "licenca": None,
                    "homepage": None,
                    "repo": repos[0] if repos else None,
                    "lojas": [],
                    "aparicoes": [],
                }
                apps[key] = entry
                by_base.setdefault(nbase, entry)
            entry["nome"] = base or entry["nome"]
            if not entry["descricao_curta"] and a["qual"]:
                entry["descricao_curta"] = " ".join(a["qual"])
            if not entry["repo"] and repos:
                entry["repo"] = repos[0]
            existentes = {(l["tipo"], l["url"]) for l in entry["lojas"]}
            for u in lojas:
                tipo = classify_url(u)
                if (tipo, u) not in existentes:
                    entry["lojas"].append({"tipo": tipo, "url": u})
                    existentes.add((tipo, u))
            tempo = match_tempo({"nome": base}, tsmap) or match_tempo(a, tsmap)
            dup = any(x["videoId"] == vid for x in entry["aparicoes"])
            if not dup:
                entry["aparicoes"].append({**vinfo, "tempo": tempo})
        time.sleep(0.3)
        if (i + 1) % 20 == 0:
            print(f"   {i + 1}/{len(candidatos)} vídeo(s)...")

    # 3) memoriza exclusões: comprovadamente fora da série
    novos_exc, purga_auto = merge_excludes(excludes, excludes_pend, uploads_fora, pl_todos)
    purga_total = purga_cache + purga_auto
    if novos_exc or purga_total or excludes_dirty:
        removidas = purgar_video_cache(vidcache, purga_total)
        save_video_cache(vidcache)
        save_excludes(excludes)
        print(f"== excludes.json: {len(excludes)} vídeo(s) ignoráveis ({len(novos_exc)} novos)")
        if removidas:
            print(f"   video-cache purgado: {len(removidas)} entradas")

    # guarda de segurança: nunca piorar o JSON antigo (inválida em --fresh)
    out_path = os.path.join(DATA_DIR, "apps.json")
    if os.path.exists(out_path) and not force and not fresh:
        with open(out_path, encoding="utf-8") as f:
            old = json.load(f)
        n_old = len(old.get("videos") or [])
        if len(videos_out) < n_old:
            print(f"ABORTADO: novos vídeos ({len(videos_out)}) < anteriores ({n_old}). "
                  f"Use --force para forçar.")
            sys.exit(1)

    # 2.95) correções manuais do repo-cache (`manual@nome`, via --app-link)
    # reaplicam-se a CADA rodada — o CI não desfaz sua curadoria
    mcache = load_cache()
    manuais = aplicar_manuais_cache(apps, mcache)
    if manuais:
        print(f"== correções manuais reaplicadas: {len(manuais)}")
        for nome, url in manuais[:8]:
            print(f"   {nome} ← {url}")
        if len(manuais) > 8:
            print(f"   … +{len(manuais) - 8}")

    # 3) enriquecimento repos --------------------------------------------
    if not sem_repo:
        print("== Enriquecendo com APIs de repositórios (paralelo)...")
        cache = load_cache()
        # caminho rápido: GitHub em LOTE via GraphQL (1 chamada por 100 repos);
        # usa GITHUB_TOKEN/GH_TOKEN/GH_PAT (no Actions: injetado de graça)
        tok = gh_token()
        rate_stop = {"stop": False}
        if tok:
            try:
                n = lookup_graphql_github(apps, cache, tok)
                print(f"   GraphQL: {n} repos github buscados em lote")
                save_cache(cache)
            except Exception as ex:
                print(f"   AVISO: GraphQL indisponível ({ex}); seguindo individual")

        # resgate: app sem fonte nem descrição (capítulos antigos, Play sem desc)
        # → tenta achar o repo pela busca do GitHub; negativo fica avisado lá embaixo
        sem_fonte = [e for e in apps.values() if sem_info(e)]
        if sem_fonte:
            print(f"== {len(sem_fonte)} app(s) sem fonte nem descrição: resgate na busca do GitHub...")
            resgat, falharam = [], []
            for e in sem_fonte:
                if rate_stop["stop"]:
                    falharam.append(e["nome"])
                    continue
                url = lookup_busca_repo(e["nome"], cache, rate_stop)
                if url:
                    e["repo"], e["origem_repo"] = url, "busca"
                    resgat.append(e["nome"])
                else:
                    falharam.append(e["nome"])
            if resgat:
                print(f"   resgatado(s) pela busca ({len(resgat)}): {', '.join(resgat[:8])}"
                      f"{'…' if len(resgat) > 8 else ''}")
            save_cache(cache)

        tasks = tarefas_enriquecimento(apps)
        cache_lock = threading.Lock()
        n_done = [0]

        def do(t):
            kind, e = t[0], t[1]
            if rate_stop["stop"]:
                return kind, e, None
            if kind == "repo":
                r = lookup_repo(e["repo"], cache, rate_stop)
            elif kind == "loja":
                r = lookup_loja_page(t[2], cache)
            else:
                r = lookup_fdroid(t[2], cache)
            with cache_lock:
                n_done[0] += 1
                if n_done[0] % 40 == 0:
                    save_cache(cache)
                    print(f"   {n_done[0]}/{len(tasks)} consultados...")
            return kind, e, r

        ok = 0
        try:
            with ThreadPoolExecutor(max_workers=8) as ex:
                for kind, e, info in ex.map(do, tasks):
                    if not info or "erro" in info:
                        continue
                    aplicar_info(e, info, idioma=(kind == "repo"))
                    ok += 1
        finally:
            save_cache(cache)
        done = sum(1 for e in apps.values() if e["descricao_repo"])
        print(f"   apps enriquecidos nesta rodada: {ok}; com descrição: {done}/{len(apps)}")

    # 4) finaliza ----------------------------------------------------------
    for e in apps.values():
        es = sorted(e["aparicoes"], key=lambda x: (x.get("data") or "", x["videoId"]), reverse=True)
        e["aparicoes"] = es
        e["data_ultima"] = (es[0].get("data") if es else None)
        e["thumbnail"] = es[0]["thumbnail"] if es else None
        # flag só quando vale flag: ausente = app com fonte/descrição normais
        if sem_info(e):
            e["sem_info"] = True

    videos_out.sort(key=lambda v: (v["data"] or "", v["videoId"]), reverse=True)
    apps_list = sorted(apps.values(),
                       key=lambda e: ((e.get("data_ultima") or ""), e["nome"]),
                       reverse=True)

    out = {
        "atualizado": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "canal": {"nome": CHANNEL_NAME, "id": CHANNEL_ID,
                  "url": f"https://www.youtube.com/@VegaData_c"},
        "playlists": PLAYLISTS,
        "videos": videos_out,
        "apps": apps_list,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    n_pl_sum = sum(len(e["aparicoes"]) for e in apps_list)
    print(f"\nOK: apps.json gerado — {len(videos_out)} vídeos, "
          f"{len(apps_list)} apps, {n_pl_sum} aparições app↔vídeo")
    if pulados_velhos:
        print(f"   ({pulados_velhos} vídeo(s) fora de playlist ignorados pela janela de {janela} mês(es))")
    if pulado_por_exclude:
        print(f"   ({pulado_por_exclude} vídeo(s) pulados via excludes.json)")
    sem_fonte_list = [e["nome"] for e in apps_list if sem_info(e)]
    if sem_fonte_list:
        print(f"   aviso: {len(sem_fonte_list)} app(s) sem fonte nem descrição "
              f"(dica: python3 src/gerar.py --sem-info lista todos): "
              f"{', '.join(sem_fonte_list[:8])}{'…' if len(sem_fonte_list) > 8 else ''}")
    if sem_repo:
        print("(enriquecimento de repos pulado: --sem-repo)")


if __name__ == "__main__":
    main()
