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
        # Puntería: los 10 jugadores, y la tuya cerca de lo que marca Leetify para esta partida (20 % total, 30 % cabeza).
        from cs2stats.metrics import aim_summary
        self.assertEqual(len(match["aim"]), 10)
        aim = aim_summary(match["aim"][str(DEMO_ME)])
        self.assertAlmostEqual(aim["accuracy"], 0.20, delta=0.02)
        self.assertAlmostEqual(aim["head_accuracy"], 0.30, delta=0.03)
        self.assertLess(aim["crosshair"], 8)
        self.assertTrue(250 < aim["time_to_damage"] < 800)
        # Impacto, duelos y utilidad: tu impacto da positivo (Leetify marca +3,83) y las kills cuadran con la tabla.
        from cs2stats.metrics import player_numbers
        mine = player_numbers(match, DEMO_ME)
        self.assertGreater(mine["impact"], 0)
        self.assertEqual(len(match["detail"]["impact"][str(DEMO_ME)]["rounds"]), 22)  # en la 2 arrancaste muerto
        self.assertEqual(sum(1 for k in match["detail"]["kills"] if k[1] == str(DEMO_ME)), 18)
        self.assertTrue(20 <= mine["utility_rating"] <= 50)
        spent, deaths = match["detail"]["unused"][str(DEMO_ME)]
        self.assertEqual(deaths, 14)  # 15 muertes, pero una fue con la ronda ya terminada
        self.assertAlmostEqual(spent / deaths, 253, delta=60)

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


class AimTest(unittest.TestCase):
    def test_resumen(self):
        from cs2stats.metrics import aim_summary
        raw = {"shots": 200, "hits": 40, "seen_shots": 100, "seen_hits": 30, "first_shots": 50, "first_hits": 15,
               "spray_shots": 50, "spray_hits": 15, "strafe_shots": 50, "strafe_ok": 40, "gun_hits": 40, "head_hits": 10,
               "ttd_sum": 5000.0, "ttd_n": 10, "xhair_sum": 60.0, "xhair_n": 12}
        aim = aim_summary(raw)
        self.assertEqual((aim["accuracy"], aim["seen_accuracy"], aim["head_accuracy"]), (0.2, 0.3, 0.25))
        self.assertEqual((aim["time_to_damage"], aim["crosshair"], aim["counter_strafe"]), (500.0, 5.0, 0.8))
        self.assertIsNone(aim_summary({}))

    def test_sin_disparos(self):
        from cs2stats.metrics import aim_summary
        raw = dict.fromkeys(("shots", "hits", "seen_shots", "seen_hits", "first_shots", "first_hits", "spray_shots",
                             "spray_hits", "strafe_shots", "strafe_ok", "gun_hits", "head_hits", "ttd_sum", "ttd_n",
                             "xhair_sum", "xhair_n"), 0)
        self.assertIsNone(aim_summary(raw)["accuracy"])


class DetailTest(unittest.TestCase):
    def test_probabilidad(self):
        from cs2stats.parser import win_chance_t
        self.assertAlmostEqual(win_chance_t(5, 5, False), 0.5)
        self.assertGreater(win_chance_t(5, 4, False), 0.5)
        self.assertGreater(win_chance_t(2, 2, True), win_chance_t(2, 2, False))
        self.assertEqual((win_chance_t(3, 0, False), win_chance_t(0, 3, False)), (1.0, 0.0))

    def test_nota_de_utilidad(self):
        from cs2stats.metrics import utility_rating
        stats = {"rounds": 20, "util_thrown": 40, "flashes": 10, "hes": 5, "enemies_flashed": 10, "blind_time": 25.0,
                 "he_damage": 100.0, "team_flashed": 0, "smokes": 15, "molotovs": 10}
        good = utility_rating(stats)
        bad = utility_rating({**stats, "enemies_flashed": 1, "blind_time": 1.0, "team_flashed": 8})
        self.assertGreater(good["rating"], bad["rating"])
        self.assertAlmostEqual(good["rating"] ** 2, good["quality"] * good["quantity"], delta=0.01)
        self.assertEqual(utility_rating({"rounds": 20, "util_thrown": 0})["rating"], 0)

    def test_impacto(self):
        from cs2stats.metrics import impact_rating
        entry = {"rounds": {"1": 0.2, "2": -0.1, "13": 0.3}, "sides": {"1": "CT", "2": "CT", "13": "T"}, "cats": {"opening": 0.2}}
        impact = impact_rating(entry)
        self.assertAlmostEqual(impact["total"], 40 / 3)
        self.assertAlmostEqual(impact["CT"], 5)
        self.assertAlmostEqual(impact["T"], 30)
        self.assertIsNone(impact_rating(None)["total"])


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


def fake_replay_round(n, kills=(), shots=None, blinds=(), length=90.0, end=80.0):
    teams = {str(ME): "T", "2": "T", "3": "T", "11": "CT", "12": "CT", "13": "CT"}
    return {"n": n, "winner": "T", "reason": "", "end": end, "length": length, "teams": teams,
            "tracks": {p: [0, 0, 0, 100] * 4 for p in teams}, "kills": list(kills), "shots": shots or {},
            "blinds": list(blinds), "nades": [], "bomb": []}


class JugadasTest(unittest.TestCase):
    def test_multikill_clutch_y_errores(self):
        from cs2stats.replay import find_moments
        me = str(ME)
        data = {"me": me, "rounds": [
            # 3 kills tuyas, pero la primera lejos de las otras: el clip no pasa de 25 s.
            fake_replay_round(1, kills=[[5.0, me, "11", "ak47", True], [40.0, me, "12", "ak47", False],
                                        [44.0, me, "13", "ak47", False]]),
            # Clutch: mueren tus 2 compañeros y ganás.
            fake_replay_round(2, kills=[[10.0, "11", "2", "awp", False], [20.0, "12", "3", "awp", False],
                                        [30.0, me, "11", "ak47", True]]),
            # Moriste sin disparar y tu flash cegó a 2 compañeros.
            fake_replay_round(3, kills=[[15.0, "11", me, "awp", True]], shots={me: [20.0]},
                              blinds=[[8.0, me, "2", 2.0], [8.05, me, "3", 1.5], [8.0, me, "12", 3.0]]),
        ]}
        rounds = [fake_round(1, kills=3, won=True), fake_round(2, kills=1, won=True, clutch_vs=1, clutch_won=True),
                  fake_round(3, died=True)]
        rounds[2]["death_time"] = 15.0
        kinds = {(m["kind"], m["round"]): m for m in find_moments(data, rounds)}
        self.assertIn(("3k", 1), kinds)
        self.assertLessEqual(kinds[("3k", 1)]["to"] - kinds[("3k", 1)]["from"], 25)
        self.assertIn(("clutch", 2), kinds)
        self.assertEqual(kinds[("clutch", 2)]["at"], 20.0)
        self.assertIn(("no_shots", 3), kinds)
        self.assertEqual(kinds[("team_flash", 3)]["count"], 2)

    def test_repeticion_comprimida(self):
        from cs2stats.replay import decode, encode
        data = {"rounds": [fake_replay_round(1)], "moments": []}
        self.assertEqual(decode(encode(data)), data)


def fake_match(played_at, map_name="de_mirage", result="W", **stats):
    s = summarize([fake_round(i, won=result == "W") for i in range(1, 21)])
    s.update(stats)
    return {"id": hash(played_at) % 10000, "played_at": played_at, "map": map_name, "result": result, "s": s,
            "scoreboard": [], "rounds": []}


def session_rows(day, results, hour=20):
    return [{"played_at": f"2026-{day}T{hour + i // 2:02d}:{(i % 2) * 45:02d}:00", "result": r, "k": 15, "d": 15, "rating": 1.0}
            for i, r in enumerate(results)]


class SesionesTest(unittest.TestCase):
    def days(self, count):
        return [f"{month:02d}-{day:02d}" for month in range(1, 5) for day in range(1, 26)][:count]

    def test_corta_por_tiempo_y_descarta_fechas_falsas(self):
        from cs2stats.sessions import split_sessions
        rows = session_rows("10-01", "WL") + session_rows("10-02", "W")
        rows.append({"played_at": "2026-10-03T14:00:00", "result": "W", "date_ok": False})
        self.assertEqual([len(s) for s in split_sessions(rows)], [2, 1])

    def test_detecta_el_cansancio_y_cuando_cortar(self):
        from datetime import datetime
        from cs2stats.sessions import analyze_sessions, current_advice
        rows = [row for day in self.days(30) for row in session_rows(day, "WWLL")]
        report = analyze_sessions(rows)
        self.assertEqual(report.stop_after, 3)
        self.assertEqual(report.findings[0].key, "fatigue")
        today = session_rows("10-20", "WW")
        report = analyze_sessions(rows[:0] + [r for r in rows] + today, datetime(2026, 10, 20, 21, 0))
        self.assertEqual(len(report.current), 2)
        self.assertIn("3", current_advice(report))

    def test_sin_muestra_no_saca_conclusiones(self):
        from cs2stats.sessions import analyze_sessions
        report = analyze_sessions([row for day in self.days(4) for row in session_rows(day, "WWLL")])
        self.assertIsNone(report.stop_after)
        self.assertEqual(report.findings, [])

    def test_vacio(self):
        from cs2stats.sessions import analyze_sessions
        self.assertEqual(analyze_sessions([]).games, 0)


class FechasTest(unittest.TestCase):
    def test_corrige_la_hora_de_importacion_con_el_historial(self):
        from cs2stats.store import Store
        with tempfile.TemporaryDirectory() as folder:
            store = Store(Path(folder) / "t.db")
            for key, played, url in (("mala", "2026-10-26T14:34:20", "u1"), ("buena", "2026-10-20T10:00:00", "u2")):
                store.db.execute("INSERT INTO matches (match_key, steamid, played_at, imported_at) VALUES (?,1,?,?)",
                                 (key, played, "2026-10-26T14:34:20"))
                store.db.execute("INSERT INTO sharecodes (code, match_key, demo_url) VALUES (?,?,?)", (key, key, url))
                store.db.execute("INSERT INTO history (key, played_at, demo_url) VALUES (?,?,?)", (key, "2026-10-26T03:33:54", url))
            self.assertEqual(store.repair_played_at(), 1)
            rows = dict(store.db.execute("SELECT match_key, played_at FROM matches").fetchall())
            store.db.close()
        self.assertEqual(rows, {"mala": "2026-10-26T03:33:54", "buena": "2026-10-20T10:00:00"})


class AbrirEnCs2Test(unittest.TestCase):
    class FakeConsole:
        def __init__(self, replies):
            self.replies, self.sent = list(replies), []

        def push(self, command):
            self.sent.append(command)

        def drain(self):
            return self.replies.pop(0) if self.replies else ""

        def close(self):
            pass

    def test_espera_la_carga_y_confirma_el_tick(self):
        from unittest import mock
        from cs2stats import demoview
        console = self.FakeConsole(["Client: Connected [DEMO]", "Demo Skipping finished at tick 0", "Demo Skipping finished at tick 5000"])
        with mock.patch.object(demoview.time, "sleep"):
            self.assertTrue(demoview.jump(console, 5000, 'Yo "x"'))
        # Un salto que cae en otro tick (el 0, durante la carga) no cuenta como llegada: se sigue esperando el pedido.
        self.assertEqual(console.replies, [])
        self.assertEqual(console.sent, ["status", "demo_gototick 5000 0 0", 'spec_player "Yo x"'])

    def test_no_pide_saltar_mientras_carga(self):
        from unittest import mock
        from cs2stats import demoview
        console = self.FakeConsole([])
        with mock.patch.object(demoview.time, "sleep"), mock.patch.object(demoview, "_wait", return_value="Client: loading"):
            self.assertFalse(demoview.jump(console, 5000, "", timeout=0))
        self.assertNotIn("demo_gototick 5000 0 0", console.sent)

    def test_vuelve_a_cargar_si_la_demo_se_cerro(self):
        from unittest import mock
        from cs2stats import demoview
        console = self.FakeConsole([])
        with mock.patch.object(demoview, "cs2_game_dir", return_value=Path("C:/x")), \
                mock.patch.object(demoview, "prepare_demo", return_value=(Path("a.dem"), "replays/a.dem")), \
                mock.patch.object(demoview, "target_tick", return_value=5000), \
                mock.patch.object(demoview, "cs2_running", return_value=True), \
                mock.patch.object(demoview, "_connect", return_value=console), \
                mock.patch.object(demoview, "_demo_playing", return_value=False), \
                mock.patch.object(demoview, "_loaded", "replays/a.dem"), \
                mock.patch.object(demoview, "jump", return_value=True), \
                mock.patch.object(demoview.time, "sleep"):
            result = demoview.open_moment(None, {"my_name": "yo"}, 3, 10.0, lambda _text: None)
        self.assertEqual(result.commands, [])
        self.assertIn('playdemo "replays/a.dem"', console.sent)

    def test_cs2_abierto_a_mano_no_se_toca(self):
        from unittest import mock
        from cs2stats import demoview
        with mock.patch.object(demoview, "cs2_game_dir", return_value=Path("C:/x")), \
                mock.patch.object(demoview, "prepare_demo", return_value=(Path("a.dem"), "replays/a.dem")), \
                mock.patch.object(demoview, "target_tick", return_value=5000), \
                mock.patch.object(demoview, "cs2_running", return_value=True), \
                mock.patch.object(demoview, "_connect", return_value=None), \
                mock.patch.object(demoview, "launch_for_demo") as launch:
            result = demoview.open_moment(None, {"my_name": "yo"}, 3, 10.0, lambda _text: None)
        launch.assert_not_called()
        self.assertEqual(result.commands, ['playdemo "replays/a.dem"', "demo_gototick 5000 0 0"])


class EntrenamientoTest(unittest.TestCase):
    def test_retos_de_la_semana(self):
        from datetime import datetime
        from cs2stats.training import week_start, weekly_challenges
        now = datetime(2026, 10, 29, 12, 0)
        self.assertEqual(week_start(now), datetime(2026, 10, 26))
        before = [fake_match(f"2026-10-{d:02d}T20:00:00", adr=60, team_flashed=4, flashes=10, trade_kills=5) for d in range(10, 25)]
        week = [fake_match(f"2026-10-{d}T20:00:00", adr=90, team_flashed=0, flashes=5) for d in (26, 27, 28)]
        challenges, start = weekly_challenges(before + week, now)
        self.assertEqual(len(challenges), 3)
        self.assertEqual(len({c.key for c in challenges}), 3)
        keys = {c.key: c for c in challenges}
        # Con ADR bajo y muchas flashes a tu equipo, esos retos van primero; esta semana ya los cumpliste.
        self.assertIn("adr", keys)
        self.assertIn("clean_flash", keys)
        self.assertTrue(keys["adr"].done and keys["clean_flash"].done)
        # Los retos no cambian con las partidas de la misma semana.
        again, _ = weekly_challenges(before + week[:1], now)
        self.assertEqual([c.key for c in again], [c.key for c in challenges])

    def test_mapas_del_workshop(self):
        from cs2stats.training import WORKOUTS, recommend
        self.assertTrue(all(w.workshop_id > 3_000_000_000 for w in WORKOUTS.values()))
        picks = recommend([], [])
        self.assertTrue(picks and all(not weak for _w, _r, weak in picks))


class PrePartidaTest(unittest.TestCase):
    def test_lee_lo_que_pegas(self):
        from cs2stats.prematch import parse_people
        text = ("https://steamcommunity.com/profiles/76561198000000001\nhttps://steamcommunity.com/id/alguien\n"
                "#  3 0:12 40 0 active 786432 'Pepe Malo'\nfulano\nhttps://www.faceit.com/es/cs2/room/"
                "1-11111111-2222-3333-4444-555555555555")
        people, vanities, room = parse_people(text, {"pepe malo": (76561198000000002, "Pepe Malo")})
        self.assertEqual([p.steamid for p in people], [76561198000000001, 76561198000000002, 0])
        self.assertEqual(people[2].name, "fulano")
        self.assertEqual(vanities, ["alguien"])
        self.assertEqual(room, "1-11111111-2222-3333-4444-555555555555")

    def test_sugiere_mapas_y_rivales(self):
        from cs2stats.prematch import analyze
        rival = 76561198000000005
        matches = []
        for _ in range(6):
            # El rival jugó en contra tuyo en Mirage y te ganó siempre, matando con AWP.
            board = [{"steamid": ME, "me": True, "ally": True, "stats": summarize([fake_round(1)])},
                     {"steamid": rival, "me": False, "ally": False, "name": "Rival",
                      "stats": summarize([fake_round(1, kills=2, died=False, opening="kill")])}]
            matches.append({"map": "de_mirage", "result": "L", "scoreboard": board,
                            "detail": {"kills": [[1, str(rival), str(ME), "awp", True]] * 3}})
        games = [{"map": "Inferno", "result": "W"}] * 10 + [{"map": "Mirage", "result": "L"}] * 10
        report = analyze(ME, [], [{"name": "Rival", "steamid": rival}], matches, games)
        verdicts = {r["map"]: r["verdict"] for r in report["maps"]}
        self.assertEqual(verdicts["inferno"], "pick")
        self.assertEqual(verdicts["mirage"], "ban")
        self.assertIn("awp", report["rivals"][0]["tags"])


class SinergiaTest(unittest.TestCase):
    def test_con_y_sin_tu_amigo(self):
        from cs2stats.friends import friends, synergy, team_roles
        friend = 76561198000000007
        stats = summarize([fake_round(i, enemies_flashed=2, trade_kills=1) for i in range(1, 11)])
        matches = []
        for i in range(6):
            together = i < 4
            board = [{"steamid": ME, "me": True, "ally": True, "stats": stats}]
            if together:
                board.append({"steamid": friend, "me": False, "ally": True, "name": "Amigo", "stats": stats})
            matches.append({"id": i, "result": "W" if together else "L", "scoreboard": board})
        found = friends(matches)
        data = synergy(found[0], matches)
        self.assertEqual((data["with"], data["without"], data["apart"]), (1.0, 0.0, 2))
        self.assertAlmostEqual(data["flashes_pr"], 2.0)
        roles = team_roles(found, found[0]["mine"], "Yo")
        self.assertEqual(len(roles["entry"]), 2)


class FaceitTest(unittest.TestCase):
    """Con respuestas armadas con el formato de la API de datos de FACEIT (v4)."""

    PLAYER = {"player_id": "yo-123", "nickname": "Yo", "faceit_url": "https://www.faceit.com/{lang}/players/Yo",
              "games": {"cs2": {"faceit_elo": 1580, "skill_level": 8, "region": "SA"}}}
    HISTORY = {"items": [{"match_id": "1-aaa", "status": "FINISHED", "started_at": 1761700000, "finished_at": 1761702400},
                         {"match_id": "1-bbb", "status": "CANCELLED", "started_at": 1761600000, "finished_at": 0}]}
    STATS = {"rounds": [{"round_stats": {"Map": "de_mirage", "Score": "13 / 9"}, "teams": [
        {"team_stats": {"Final Score": "9"}, "players": [{"player_id": "otro", "nickname": "Rival", "player_stats": {}}]},
        {"team_stats": {"Final Score": "13"}, "players": [
            {"player_id": "yo-123", "nickname": "Yo", "player_stats": {"Kills": "21", "Deaths": "14", "Assists": "4",
                                                                       "Headshots %": "52", "ADR": "88.4", "MVPs": "3",
                                                                       "Result": "1"}},
            {"player_id": "amigo", "nickname": "Amigo", "player_stats": {}}]}]}]}

    def fake_get(self, url, headers=None):
        if "/stats" in url:
            return self.STATS
        if "/history" in url:
            return self.HISTORY
        return self.PLAYER

    def test_trae_tus_partidas_separadas(self):
        from unittest import mock
        from cs2stats import faceit
        from cs2stats.store import Settings, Store
        home = Path(tempfile.mkdtemp(prefix="cs2stats-faceit-"))
        store, settings = Store(home / "h.db"), Settings(home / "a.json")
        settings.set("steamid", ME)
        settings.set("faceit_key", "x" * 36)
        with mock.patch.object(faceit, "_get", self.fake_get):
            self.assertEqual(faceit.sync_faceit(store, settings, lambda _text: None), 1)
            self.assertEqual(faceit.sync_faceit(store, settings, lambda _text: None), 0)   # no repite partidas
        rows = store.history(ME)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["mode"], row["map"], row["result"], row["score_us"], row["score_them"]),
                         ("faceit", "Mirage", "W", 13, 9))
        self.assertEqual((row["kills"], row["deaths"], row["hsp"], row["adr"]), (21, 14, 52, 88.4))
        self.assertEqual(settings["faceit_profile"]["level"], 8)
        self.assertEqual(store.faceit_elo()[-1]["elo"], 1580)

    def test_progreso_de_nivel(self):
        from cs2stats.faceit import level_progress
        share, missing, following = level_progress(1580)
        self.assertEqual((missing, following), (171, 9))
        self.assertIsNone(level_progress(2400))


if __name__ == "__main__":
    unittest.main()
