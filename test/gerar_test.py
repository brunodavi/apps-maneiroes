#!/usr/bin/env python3
"""
Testes de gerar.py usando descrições REAIS retiradas do YouTube.

Fixtures reais:
  - DESC_COM_TEMPOS   = "Novos APPS DIFERENCIADOS pro seu Android! (Setembro 2026)"
                        (vídeo 5vhhPU0tBy4 — header "Tempos do vídeo:")
  - DESC_SEM_HEADER   = "Aplicativos Maneirões (Janeiro 2025)"
                        (vídeo Zpk1vb2RpCM — timestamps SEM o header "Tempos do vídeo:")
  - DESC_SEM_TEMPOS   = "Aplicativos Open Source!"
                        (vídeo 1kC_XAG1fz4 — série antiga, sem timestamps)

Rodar: python3 test/gerar_test.py   (da raiz do repo)
"""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gerar import (FORA_SERIE_MOTIVO, PLAYLISTS, app_key, base_name, classify_url,
                   cutoff_date, decidir_skip_excludes, iso8601_seconds,
                   match_tempo, merge_excludes, normalize_repo_url, parse_desc,
                   purgar_video_cache)

DESC_COM_TEMPOS = """Eai pessoal, no vídeo de hoje vamos continuar a nossa série de aplicativos mensais, onde eu basicamente faço um compilado de diversos apps que eu acho interessantes, apps comuns, projetos de código aberto etc... e apresento eles pra vocês.

Vídeos da série de aplicativos:
https://www.youtube.com/playlist?list=PLfz2Tqtsq7B8TiFdg2rnAyM7vsj3pdhUo

Twine:
https://github.com/msasikanth/twine
https://play.google.com/store/apps/details?id=dev.sasikanth.rss.reader
* Open source

Network Scanner:
https://github.com/usamaiqb/network-scanner
https://play.google.com/store/apps/details?id=com.networkscanner.app
https://f-droid.org/packages/com.networkscanner.app/
* Open source

TeleDrive:
https://github.com/Mahmud0808/TeleDrive
* Open source

CodeAssist:
https://github.com/tyron12233/CodeAssist
https://play.google.com/store/apps/details?id=com.tyron.code
* Open source

Candy Browser:
https://github.com/sk2andy/candy-browser/releases
* Open source

Encerramento:
https://www.youtube.com/@VegaData_c

Tempos do vídeo:
00:00 - Introdução
00:30 - Twine
01:30 - Network Scanner
02:33 - TeleDrive
12:01 - Code Assist
15:24 - Candy Browser
16:27 - Encerramento

-

Gostou do vídeo? Dá aquele Like e inscreva-se no canal."""

DESC_SEM_HEADER = """Eai pessoal, no vídeo de hoje, vamos continuar a série de aplicativos mensais, onde mostro um compilado de diversos aplicativos, como aplicativos comuns, aplicativos de código aberto, e diversos outros apps, acho que deu pra entender, essa essa série é mensal, e todo mês teremos um vídeo com dicas de aplicativos que podem ser úteis.

Vídeos da série de aplicativos mensais:
https://www.youtube.com/playlist?list=PLfz2Tqtsq7B8TiFdg2rnAyM7vsj3pdhUo

TIDY:
https://github.com/slavabarkov/tidy
https://f-droid.org/packages/com.slavabarkov.tidy/
* Open source

Files:
https://play.google.com/store/apps/details?id=com.marc.files

BT Remote:
https://gitlab.com/Atharok/BtRemote
https://f-droid.org/packages/com.atharok.btremote/
* Open source

00:00 - TIDY
01:21 - Files
05:43 - BT Remote
13:33 - Encerramento

-

Gostou do vídeo? Dá aquele Like e inscreva-se no canal."""

DESC_SEM_TEMPOS = """Vários aplicativos de código aberto muito maneirões!
Alias, alguns desses apps não estão 100% traduzidos para o português, fiquem livres para colaborar com a comunidade!

-

F-Droid:
https://f-droid.org/en/packages/org.fdroid.fdroid/

Aurora Droid:
https://f-droid.org/packages/com.aurora.adroid/

LibreTorrent:
https://f-droid.org/pt_BR/packages/org.proninyaroslav.libretorrent/

FairEmail:
https://github.com/M66B/FairEmail/releases

MPV:
https://f-droid.org/en/packages/is.xyz.mpv/

-

Gostou do vídeo? Dá aquele Like e inscreva-se no canal."""


class TestParseDescricaoReal(unittest.TestCase):

    def test_bloco_da_intro_nao_vira_app(self):
        """O link da playlist no intro não pode criar um app "Vídeos da série..."."""
        apps, _ = parse_desc(DESC_COM_TEMPOS)
        nomes = [a["nome"] for a in apps]
        self.assertNotIn("Vídeos da série de aplicativos", nomes)
        for n in nomes:
            self.assertFalse(n.lower().startswith("vídeos da série"))
            self.assertFalse(n.lower().startswith("encerramento"))

    def test_apps_e_links_reais(self):
        apps, _ = parse_desc(DESC_COM_TEMPOS)
        nomes = {a["nome"]: a for a in apps}
        # fixture é recorte da descrição real (5 dos 14 apps do vídeo 5vhhPU0tBy4)
        self.assertEqual(len(apps), 5)
        self.assertIn("Twine", nomes)
        self.assertIn("Network Scanner", nomes)
        self.assertIn("Candy Browser", nomes)
        twine = nomes["Twine"]
        self.assertIn("https://github.com/msasikanth/twine", twine["urls"])
        self.assertIn(
            "https://play.google.com/store/apps/details?id=dev.sasikanth.rss.reader",
            twine["urls"])
        self.assertEqual(twine["qual"], ["Open source"])
        # link de /releases entra como repo do mesmo repo
        self.assertIn(
            "https://github.com/sk2andy/candy-browser/releases",
            nomes["Candy Browser"]["urls"])

    def test_tempos_com_header(self):
        _, tsmap = parse_desc(DESC_COM_TEMPOS)
        self.assertEqual(tsmap["twine"], 30)
        self.assertEqual(tsmap["networkscanner"], 90)
        self.assertEqual(tsmap["teledrive"], 153)
        self.assertEqual(tsmap["candybrowser"], 924)
        # intro e encerramento não viram capítulo de app
        self.assertNotIn("introducao", tsmap)
        self.assertNotIn("encerramento", tsmap)

    def test_match_fuzzy_name_no_capitulo(self):
        """No vídeo real o capítulo é "Code Assist" e o app "CodeAssist"."""
        apps, tsmap = parse_desc(DESC_COM_TEMPOS)
        code_assist = next(a for a in apps if a["nome"] == "CodeAssist")
        self.assertEqual(match_tempo(code_assist, tsmap), 721)

    def test_tempos_sem_header(self):
        """Vídeo real de Jan/2025 não tem o header "Tempos do vídeo:"."""
        apps, tsmap = parse_desc(DESC_SEM_HEADER)
        nomes = {a["nome"]: a for a in apps}
        self.assertEqual(len(apps), 3)
        self.assertIn("TIDY", nomes)
        self.assertIn("Files", nomes)
        self.assertIn("BT Remote", nomes)
        files = nomes["Files"]
        self.assertEqual(files["urls"], [
            "https://play.google.com/store/apps/details?id=com.marc.files"])
        self.assertEqual(match_tempo(nomes["BT Remote"], tsmap), 343)
        self.assertEqual(match_tempo(nomes["Files"], tsmap), 81)

    def test_serie_antiga_sem_tempos(self):
        apps, tsmap = parse_desc(DESC_SEM_TEMPOS)
        nomes = {a["nome"]: a for a in apps}
        self.assertEqual(len(apps), 5)
        self.assertEqual(tsmap, {})
        self.assertIn("F-Droid", nomes)
        self.assertIn("MPV", nomes)
        self.assertEqual(
            nomes["FairEmail"]["urls"],
            ["https://github.com/M66B/FairEmail/releases"])


class TestClassificacaoURL(unittest.TestCase):

    def test_repos(self):
        self.assertEqual(classify_url("https://github.com/msasikanth/twine"), "repo")
        self.assertEqual(classify_url("https://gitlab.com/yaky/android-usb-cam-viewer"), "repo")
        self.assertEqual(classify_url("https://codeberg.org/s1m/savertuner"), "repo")

    def test_lojas(self):
        self.assertEqual(
            classify_url("https://play.google.com/store/apps/details?id=x"), "loja:play")
        self.assertEqual(
            classify_url("https://f-droid.org/en/packages/is.xyz.mpv/"), "loja:fdroid")
        self.assertEqual(
            classify_url("https://www.apkmirror.com/apk/lin-jin-bin/mt-manager/"),
            "loja:apkmirror")

    def test_links_do_youtube_fora(self):
        self.assertIsNone(classify_url(
            "https://www.youtube.com/playlist?list=PLfz2Tqtsq7B8TiFdg2rnAyM7vsj3pdhUo"))
        self.assertIsNone(classify_url("https://youtu.be/5vhhPU0tBy4"))


class TestChaveDedup(unittest.TestCase):

    def test_mesmo_repo_varias_urls(self):
        """repo, repo/releases e repo/.git caem na mesma chave."""
        k1 = app_key("App", ["https://github.com/user/proj"])
        k2 = app_key("App", ["https://github.com/user/proj/releases"])
        k3 = app_key("App", ["https://github.com/user/proj.git"])
        self.assertEqual(k1, k2)
        self.assertEqual(k1, k3)

    def test_play_e_fdroid(self):
        self.assertEqual(
            app_key("Files", ["https://play.google.com/store/apps/details?id=com.marc.files"]),
            "play:com.marc.files")
        self.assertEqual(
            app_key("MPV", ["https://f-droid.org/en/packages/is.xyz.mpv/"]),
            "fdroid:is.xyz.mpv")


class TestRepoURL(unittest.TestCase):

    def test_normaliza_url_repo(self):
        self.assertEqual(
            normalize_repo_url("https://github.com/sk2andy/candy-browser/releases"),
            ("https://github.com/sk2andy/candy-browser", "github.com"))
        self.assertEqual(
            normalize_repo_url("https://codeberg.org/s1m/savertuner.git"),
            ("https://codeberg.org/s1m/savertuner", "codeberg.org"))

    def test_url_nao_repo_retorna_none(self):
        self.assertIsNone(normalize_repo_url("https://github.com/user"))


class TestNomeBase(unittest.TestCase):
    """Formato real da série antiga: o MESMO app aparece como
    "OpenBoard no GitHub:", "OpenBoard na Play Store:" etc. (vídeo n4tWRXTsMwM)."""

    def test_sufixos_reais(self):
        self.assertEqual(base_name("XClipper no F-Droid"), "XClipper")
        self.assertEqual(base_name("XClipper na Play Store"), "XClipper")
        self.assertEqual(base_name("OpenBoard no GitHub"), "OpenBoard")
        self.assertEqual(base_name("FlorisBoard no GitHub"), "FlorisBoard")
        self.assertEqual(base_name("App Manager no F-Droid"), "App Manager")
        self.assertEqual(base_name("Site oficial do Lawnchair"), "Lawnchair")

    def test_limpeza_avalia(self):
        self.assertEqual(base_name("TIDY"), "TIDY")
        self.assertEqual(base_name("Twine"), "Twine")
        self.assertEqual(base_name("Novos APPS DIFERENCIADOS pro seu Android!"), "Novos APPS DIFERENCIADOS pro seu Android!")

    def test_chave_com_nome_base(self):
        """Sem repo, "no F-Droid" e "na Play Store" devem cair numa única app."""
        k1 = app_key("XClipper", ["https://f-droid.org/en/packages/com.kpstv.xclipper/"])
        k2 = app_key("XClipper", ["https://play.google.com/store/apps/details?id=com.kpstv.xclipper"])
        self.assertNotEqual(k1, k2)  # as chaves o completo existem; a feed thì só o base


class TestRegrasCI(unittest.TestCase):

    def test_duracao_iso8601(self):
        self.assertEqual(iso8601_seconds("PT4M13S"), 253)
        self.assertEqual(iso8601_seconds("PT1H2M3S"), 3723)
        self.assertEqual(iso8601_seconds("PT1M"), 60)
        self.assertIsNone(iso8601_seconds("P1D"))
        self.assertIsNone(iso8601_seconds(""))
        self.assertIsNone(iso8601_seconds(None))

    def test_janela_de_meses(self):
        hoje = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        c1 = cutoff_date(1)
        c12 = cutoff_date(12)
        # janela de 1 mês fica a até 31 dias de distância de hoje
        d_d1 = datetime.strptime(hoje, "%Y-%m-%d") - datetime.strptime(c1, "%Y-%m-%d")
        self.assertLessEqual(abs(d_d1.days - 30), 2)
        d_d12 = datetime.strptime(hoje, "%Y-%m-%d") - datetime.strptime(c12, "%Y-%m-%d")
        self.assertLessEqual(abs(d_d12.days - 360), 2)
        self.assertIsNone(cutoff_date(0))
        self.assertIsNone(cutoff_date(None))

    def test_formato_da_data_compara_ok(self):
        # a comparação usada no filtro e em strings ISO lexicográficas
        self.assertTrue(cutoff_date(1) <= "9999-99-99")
        c = cutoff_date(3)
        self.assertLess(c, datetime.now(timezone.utc).strftime("%Y-%m-%d"))


class TestRegraExcludes(unittest.TestCase):
    """Memória negativa: playlists vencem exclude; merge é idempotente e
    preenche motivo/data; purge remove do video-cache só o que existe."""

    def setUp(self):
        self.pl_map = {PLAYLISTS[0]: ["vid-pl-1"], PLAYLISTS[1]: ["vid-pl-2"]}
        self.pl_todos = {"vid-pl-1", "vid-pl-2"}

    def test_playlist_vence_exclude(self):
        fora = FORA_SERIE_MOTIVO
        excludes = {"vid-pl-1": {"motivo": fora, "ts": "2026-10-25"},
                    "vid-definitivo": {"motivo": fora, "ts": "2026-10-25"},
                    "vid-pend": {"motivo": "título de série sem parse de apps",
                                 "ts": "2026-10-25"}}
        # mesmo excluído, se entrou em playlist não é pulado
        self.assertFalse(decidir_skip_excludes("vid-pl-1", excludes, self.pl_map))
        # excluído definitivo fora de playlist → pulado
        self.assertTrue(decidir_skip_excludes("vid-definitivo", excludes, self.pl_map))
        # pendência "sem parse" é REAVENCIÁVEL: não pula, reprocessa
        self.assertFalse(decidir_skip_excludes("vid-pend", excludes, self.pl_map))
        # nem excluído, nem playlist → processa normal
        self.assertFalse(decidir_skip_excludes("vid-novo", excludes, self.pl_map))

    def test_merge_nunca_exclui_de_playlist(self):
        excludes = {}
        novos, purga = merge_excludes(
            excludes, [("vid-pl-1", "título de série sem parse de apps")],
            [], self.pl_todos, hoje="2026-10-25")
        self.assertEqual(novos, [])
        self.assertEqual(purga, [])
        self.assertNotIn("vid-pl-1", excludes)

    def test_merge_adiciona_fora_serie_com_motivo_e_data(self):
        excludes = {}
        novos, purga = merge_excludes(
            excludes, [], [{"videoId": "vid-x"}], self.pl_todos, hoje="2026-10-25")
        self.assertEqual(novos, ["vid-x"])
        self.assertEqual(purga, ["vid-x"])  # for a da série → purge do cache
        self.assertEqual(excludes["vid-x"],
                         {"motivo": "fora da série de apps (título)", "ts": "2026-10-25"})

    def test_merge_pendente_sem_purge(self):
        """título de série mas parse vazio NÃO limpa o video-cache (reavaliável)."""
        novos, purga = merge_excludes(
            {}, [("vid-y", "título de série sem parse de apps")], [],
            self.pl_todos, hoje="2026-10-25")
        self.assertEqual(novos, ["vid-y"])
        self.assertEqual(purga, [])

    def test_merge_idempotente(self):
        excludes = {}
        for _ in range(2):
            merge_excludes(excludes, [("vid-z", "título de série sem parse de apps")],
                           [{"videoId": "vid-w"}], self.pl_todos, hoje="2026-10-25")
        self.assertEqual(len(excludes), 2)
        self.assertEqual(set(excludes), {"vid-z", "vid-w"})

    def test_purga_somente_o_que_existe(self):
        cache = {"a": {"titulo": "x"}, "c": {"titulo": "z"}}
        rem = purgar_video_cache(cache, ["a", "b", "c"])
        self.assertEqual(sorted(rem), ["a", "c"])
        self.assertEqual(cache, {})


class TestGitAtualizado(unittest.TestCase):
    """Regra de decisão do cache para popular 'data de atualização do repo'."""

    def setUp(self):
        self.pl_todos = set()

    def test_gql_necessario(self):
        from gerar import gql_necessario
        self.assertTrue(gql_necessario(None))                       # ausente → busca
        self.assertTrue(gql_necessario({"parcial": True}))          # sem data → busca
        self.assertTrue(gql_necessario({"descricao_repo": "x"}))     # antigo (sem data) → busca
        self.assertFalse(gql_necessario({"git_atualizado": "2026-10-01"}))
        # erro definitivo não gasta chamada
        self.assertFalse(gql_necessario({"erro": 404}))

    def test_cache_servivel_para_rest(self):
        from gerar import precisa_refetch_repo
        self.assertTrue(precisa_refetch_repo(None))
        self.assertFalse(precisa_refetch_repo({"parcial": True}))    # HTML fallback aceito no REST
        self.assertFalse(precisa_refetch_repo({"git_atualizado": "2026-10-01"}))
        self.assertFalse(precisa_refetch_repo({"erro": 404}))
        # entrada antiga sem data e sem flag parcial é resfreshada
        self.assertTrue(precisa_refetch_repo({"descricao_repo": "x"}))


class TestSeriesAntigas(unittest.TestCase):
    """Séries antigas fora das playlists: regex de série + apps pelos capítulos."""

    def test_regex_acha_series_antigas(self):
        from gerar import SERIES_RE
        casam = [
            "Recomendações de Apps #5",
            "#1 - Recomendações de Aplicativos para Android",
            "Aplicativos que utilizam Shizuku #1",
            "Aplicativos que precisam do ADB! #1",
            "Recomendações de Players de Música pra Android",
            "Recomendações de Lojas de Aplicativos (Alternativas a Play Store)",
            "Apps que estendem as funções do seu Android!",
        ]
        for t in casam:
            self.assertIsNotNone(SERIES_RE.search(t), t)
        nao_casam = [
            "As variantes de aplicativos",
            "Truques e Dicas no Android e em alguns Apps #2",
            "Dicas e Truques na Play Store",
            "MIUI - Dicas e Truques",
            "Um guia de como fazer root no Android com Magisk!",
        ]
        for t in nao_casam:
            self.assertIsNone(SERIES_RE.search(t), t)

    def test_apps_por_capitulos(self):
        from gerar import apps_por_capitulos
        desc = "\n".join([
            "Fiquem livres para comentar sugestões :)",
            "Tempos do vídeo:",
            "00:00 - Introdução",
            "00:40 - Activity Launcher",
            "06:57 - Privacy Dashboard",
            "09:11 - XClipper",
            "11:47 - Activity Launcher",   # repetido: dedup
        ])
        apps = apps_por_capitulos(desc)
        nomes = [a["nome"] for a in apps]
        self.assertEqual(len(nomes), 3)
        self.assertIn("Activity Launcher", nomes)
        self.assertIn("Privacy Dashboard", nomes)
        self.assertNotIn("Introdução", nomes)
        for a in apps:
            self.assertEqual(a["urls"], [])

    def test_legacy_engata_pelo_titulo(self):
        from gerar import LEGACY_CAPITULOS_RE
        self.assertIsNotNone(LEGACY_CAPITULOS_RE.search("Recomendações de Apps #6"))
        self.assertIsNotNone(LEGACY_CAPITULOS_RE.search("#3 - Recomendações de Aplicativos para Android"))
        # outros formatos antigos NÃO podem gerar apps falsos (capítulo = dica, não app)
        self.assertIsNone(LEGACY_CAPITULOS_RE.search("Truques e Dicas no Android e em alguns Apps #2"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
