"""Pruebas del lector (con tus demos reales si están en la PC), de las cuentas, los consejos y el aviso de CS2."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ["CS2STATS_HOME"] = tempfile.mkdtemp(prefix="cs2stats-test-")

from cs2stats.gsi import MatchTracker  # noqa: E402
from cs2stats.insights import analyze  # noqa: E402
from cs2stats.metrics import summarize  # noqa: E402

# Cuenta de ejemplo para las pruebas sin demo. Las pruebas con demos reales usan tu cuenta y tus archivos:
# CS2STATS_TEST_STEAMID (si no está, se saltean).
ME = 76561190000000009
DEMO_ME = int(os.environ.get("CS2STATS_TEST_STEAMID") or 0)
CSGO = Path(r"C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\csgo")
NUKE = CSGO / "replays" / "match730_003850384405725970450_0667794443_346.dem"
MIRAGE = CSGO / "1-bc5e1969-c59d-4cb5-a2cb-a64a5c6b5e88-1-1.dem"


def fake_round(n, side="T", won=False, kills=0, died=True, first=False, tradeable=True, traded=False, **extra):
    base = {"n": n, "side": side, "won": won, "reason": "", "kills": kills, "hs_kills": 0, "assists": 0,
            "flash_assists": 0, "died": died, "died_live": died, "death_time": 20.0 if died else None, "damage": 50.0,
            "util_damage": 0.0, "opening": None, "first_team_death": first, "traded": traded,
            "tradeable": tradeable and died, "trade_kills": 0, "clutch_vs": None, "clutch_won": False, "equip": 4000,
            "money": 4000, "team_equip": 4000, "buy": "completa", "team_buy": "completa", "flash": 1, "smoke": 0,
            "he": 0, "molotov": 0, "decoy": 0, "enemies_flashed": 0, "blind_time": 0.0, "team_flashed": 0,
            "kill_weapons": [], "kast": kills > 0 or not died, "map": "de_mirage", "match_id": 1}
    base.update(extra)
    return base


class ParserTest(unittest.TestCase):
    @unittest.skipUnless(DEMO_ME and NUKE.exists(), "No está la demo de Nuke")
    def test_nuke_premier(self):
        from cs2stats.parser import parse_demo
        match = parse_demo(str(NUKE), DEMO_ME)
        s = summarize(match["rounds"])
        self.assertEqual(match["source"], "premier")
        self.assertEqual((match["score_us"], match["score_them"]), (13, 10))
        self.assertEqual((s["kills"], s["deaths"], s["assists"]), (18, 15, 6))
        self.assertEqual(match["rank"]["new"], 8851)
        self.assertAlmostEqual(s["adr"], 78.1, delta=0.5)
        self.assertIn("m4a1_silencer", match["weapons"])
        self.assertGreater(match["weapons"]["m4a1_silencer"]["damage"], 0)

    @unittest.skipUnless(DEMO_ME and MIRAGE.exists(), "No está la demo de Mirage")
    def test_mirage_faceit(self):
        from cs2stats.parser import parse_demo
        match = parse_demo(str(MIRAGE), DEMO_ME)
        s = summarize(match["rounds"])
        self.assertEqual(match["source"], "faceit")
        self.assertEqual(len(match["rounds"]), 36)  # sin la ronda de cuchillo
        self.assertEqual((s["kills"], s["deaths"]), (38, 26))
        self.assertLess(s["adr"], 120)  # el daño de más ya no infla el ADR

    @unittest.skipUnless(DEMO_ME and NUKE.exists(), "No está la demo de Nuke")
    def test_otra_cuenta(self):
        from cs2stats.parser import NotInDemo, parse_demo
        with self.assertRaises(NotInDemo):
            parse_demo(str(NUKE), 76561197960265728 + 807884606)


class InsightTest(unittest.TestCase):
    def test_muere_primero(self):
        rounds = [fake_round(i, first=i % 2 == 0) for i in range(1, 21)]
        matches = [{"id": 1, "map": "de_mirage", "result": "L", "rounds": rounds, "weapons": {}}] * 3
        titles = [i.title for i in analyze(matches) if i.kind == "flojo"]
        self.assertTrue(any("Morís primero en el 50 %" in t and "Mirage" in t for t in titles), titles)

    def test_pocas_partidas_baja_confianza(self):
        rounds = [fake_round(i, first=True) for i in range(1, 80)]
        items = analyze([{"id": 1, "map": "de_mirage", "result": "L", "rounds": rounds, "weapons": {}}])
        self.assertTrue(items)
        self.assertNotIn("alta", {i.confidence for i in items})

    def test_sin_partidas(self):
        self.assertEqual(analyze([]), [])


class GsiTest(unittest.TestCase):
    def payload(self, phase, me=True):
        return {"provider": {"steamid": str(ME)},
                "map": {"name": "de_nuke", "mode": "competitive", "phase": phase,
                        "team_ct": {"score": 13}, "team_t": {"score": 10}},
                "player": {"steamid": str(ME if me else 1), "team": "CT",
                           "match_stats": {"kills": 18, "assists": 6, "deaths": 15, "mvps": 3, "score": 40}}}

    def test_avisa_una_vez(self):
        ended = []
        tracker = MatchTracker(ME, ended.append)
        tracker.feed(self.payload("live"))
        tracker.feed(self.payload("gameover", me=False))  # muerto y mirando a otro
        tracker.feed(self.payload("gameover"))
        self.assertEqual(len(ended), 1)
        self.assertEqual((ended[0]["score_us"], ended[0]["kills"]), (13, 18))

    def test_ignora_otra_cuenta(self):
        ended = []
        tracker = MatchTracker(123, ended.append)
        tracker.feed(self.payload("gameover"))
        self.assertEqual(ended, [])


GCPD_SAMPLE = """
<table class="generic_kv_table csgo_scoreboard_root"><tbody><tr><td class="val_left">
<table class="csgo_scoreboard_inner_left"><tbody>
<tr><td>Premier Ancient</td></tr><tr><td>2026-10-20 23:10:05 GMT</td></tr>
<tr><td>Wait Time: 00:45</td></tr><tr><td>Match Duration: 38:20</td></tr>
<tr><td><a href="http://replay181.valve.net/730/003850000000000000001_0123456789.dem.bz2"><div class="csgo_scoreboard_btn_gotv">Download GOTV Replay</div></a></td></tr>
</tbody></table></td><td class="val_right"><table class="csgo_scoreboard_inner_right"><tbody>
<tr><th>Player Name</th><th>Ping</th><th>K</th><th>A</th><th>D</th><th>&#9733;</th><th>HSP</th><th>Score</th></tr>
<tr><td class="inner_name"><a class="linkTitle" href="https://steamcommunity.com/profiles/76561190000000009">Jugador</a></td><td>30</td><td>22</td><td>4</td><td>15</td><td>&#9733;3</td><td>45%</td><td>55</td></tr>
<tr><td class="inner_name"><a class="linkTitle" href="https://steamcommunity.com/profiles/76561190000000001">Amigo</a></td><td>40</td><td>15</td><td>6</td><td>16</td><td></td><td>30%</td><td>40</td></tr>
<tr><td colspan="8" class="csgo_scoreboard_score">13 : 9</td></tr>
<tr><td class="inner_name"><a class="linkTitle" href="https://steamcommunity.com/profiles/76561190000000002">Rival</a></td><td>50</td><td>18</td><td>2</td><td>19</td><td>&#9733;2</td><td>50%</td><td>45</td></tr>
</tbody></table></td></tr></tbody></table>
"""


class SteamTest(unittest.TestCase):
    def test_historial(self):
        from cs2stats.steamapi import parse_history
        rows = parse_history(GCPD_SAMPLE, ME, "premier")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["map"], row["score_us"], row["score_them"], row["result"]), ("Ancient", 13, 9, "W"))
        self.assertEqual((row["kills"], row["assists"], row["deaths"], row["mvps"], row["hsp"]), (22, 4, 15, 3, 45))
        self.assertTrue(row["demo_url"].endswith(".dem.bz2"))
        self.assertEqual([p["name"] for p in row["team"]], ["Amigo"])

    def test_codigo_de_partida(self):
        from cs2stats.steamapi import clean_sharecode
        self.assertEqual(clean_sharecode(" steam://rungame/730/x/+csgo_download_match%20CSGO-abcde-ABCDE-12345-fghij-67890 "),
                         "CSGO-abcde-ABCDE-12345-fghij-67890")
        self.assertEqual(clean_sharecode("cualquier cosa"), "")

    def test_cookies_de_la_comunidad(self):
        from cs2stats.steamapi import cookie_header
        cookies = ["steamLoginSecure=comunidad; Path=/; Secure; HttpOnly; Domain=steamcommunity.com",
                   "steamLoginSecure=tienda; Path=/; Secure; HttpOnly; Domain=store.steampowered.com",
                   "steamRefresh_steam=refresco; Path=/; Domain=login.steampowered.com",
                   "sessionid=abc; Path=/; Secure; Domain=steamcommunity.com",
                   "sessionid=abc; Path=/; Secure; Domain=store.steampowered.com"]
        header, session = cookie_header(cookies)
        self.assertEqual(header, "steamLoginSecure=comunidad; sessionid=abc")
        self.assertEqual(session, "abc")

    def test_cifrado(self):
        from cs2stats.secure import protect, unprotect
        secret = protect("clave-de-prueba")
        self.assertNotIn("clave", secret)
        self.assertEqual(unprotect(secret), "clave-de-prueba")


class RankTest(unittest.TestCase):
    def test_percentil(self):
        from cs2stats.benchmarks import compare
        samples = [{"premier": 8000 + i * 10, "values": {"adr": 60.0 + i, "rating": 0.8 + i / 50}} for i in range(20)]
        comps, reference, n = compare({"adr": 75.0, "rating": 1.3, "rounds": 100}, samples, 8500)
        adr = next(c for c in comps if c.metric.key == "adr")
        self.assertIn("celeste", reference)
        self.assertEqual(n, 20)
        self.assertAlmostEqual(adr.average, 69.5)
        self.assertGreater(adr.score, 70)

    @unittest.skipUnless(DEMO_ME and NUKE.exists(), "No está la demo de Nuke")
    def test_rating_de_los_rivales(self):
        from cs2stats.parser import parse_demo
        match = parse_demo(str(NUKE), DEMO_ME)
        others = [p for p in match["scoreboard"] if not p["me"]]
        self.assertEqual(len(others), 9)
        self.assertTrue(any(p["premier"] for p in others))
        self.assertTrue(all("rating" in p["stats"] for p in others))


class LatasTest(unittest.TestCase):
    def test_lista_de_latas(self):
        from cs2stats.nades import load_lineups
        lineups = load_lineups()
        self.assertGreater(len(lineups), 50)
        self.assertEqual(len({l.id for l in lineups}), len(lineups))
        self.assertTrue(all(len(l.steps) >= 3 and l.side in ("T", "CT", "") for l in lineups))
        self.assertTrue(any(l.title == "Smoke Ventana" and l.map == "de_mirage" for l in lineups))

    def test_cuenta_tus_tiros(self):
        from cs2stats.nades import build_lineups, load_lineups
        ventana = next(l for l in load_lineups() if l.title == "Smoke Ventana")
        x, y, z = ventana.pos
        throw = {"type": "smoke", "pos": [x + 10, y, z - 64], "ang": [ventana.ang[0] + 1, ventana.ang[1] - 1],
                 "land": None, "me": True}
        far = dict(throw, pos=[x + 400, y, z])
        lineups, _ = build_lineups([{"map": "de_mirage", "grenades": [throw, far], "grid": []}])
        found = next(l for l in lineups["de_mirage"] if l.id == ventana.id)
        self.assertEqual((found.count, found.mine), (1, 1))


if __name__ == "__main__":
    unittest.main()
