"""Detecta puntos flojos y fuertes con números concretos y propone qué practicar.

Cada regla mira una muestra mínima: con pocas rondas el consejo se marca como poco confiable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .i18n import language, t
from .metrics import by_key, map_label, summarize, weapon_label

SNIPERS = {"awp", "ssg08", "g3sg1", "scar20"}
RIFLES = {"ak47", "m4a1", "m4a1_silencer", "galilar", "famas", "aug", "sg556"}


@dataclass
class Insight:
    kind: str            # "flojo" o "fuerte"
    area: str
    title: str
    detail: str
    advice: list[str] = field(default_factory=list)
    score: float = 0.0
    sample: int = 0
    unit: str = "rondas"
    matches: int = 99

    @property
    def confidence(self) -> str:
        high, mid = {"rondas": (60, 25), "duelos": (20, 8), "muertes": (25, 10), "partidas": (8, 4),
                     "flashes": (30, 12), "balas": (300, 120), "kills": (60, 25), "clutches": (12, 5)}.get(self.unit, (60, 25))
        level = "alta" if self.sample >= high else "media" if self.sample >= mid else "baja"
        # Con una o dos partidas, un mal día pesa demasiado: nunca más que confianza media.
        return "media" if level == "alta" and self.matches < 3 else level


def pct(value: float) -> str:
    return f"{round(value * 100):.0f}%" if language() == "en" else f"{round(value * 100):.0f} %"


def num(value: float, decimals: int = 1) -> str:
    text = f"{value:.{decimals}f}"
    return text if language() == "en" else text.replace(".", ",")


def _weight(sample: int, full: int) -> float:
    return min(1.0, math.sqrt(sample / full))


ADVICE_FIRST_DEATH = {
    "T": [t("No seas el primero en asomar sin ayuda: pedí una flash o jugá de segundo para poder cambiar la kill."),
          t("En las tomas entrá pegado al que abre: a menos de 5 segundos de distancia, así vengás su muerte o él la tuya."),
          t("Si no hay información, esperá a que tu equipo tire utilidad antes de pelear por el control del mapa.")],
    "CT": [t("Evitá los piques agresivos al principio de la ronda: dejá que vengan y jugá desde un ángulo que cubra un compañero."),
           t("Después de mostrarte en un ángulo, cambiá de lugar: no repitas el mismo pique."),
           t("Frená la entrada con una molotov o una HE en vez de pelear el primer duelo sin ayuda.")],
}


def analyze(matches: list[dict]) -> list[Insight]:
    rounds = [r for m in matches for r in m["rounds"]]
    if not rounds:
        return []
    found: list[Insight] = []
    total = summarize(rounds)

    # 1. Quién cae primero en el equipo, por mapa y lado.
    flagged_sides = set()
    groups = by_key(rounds, lambda r: (r["map"], r["side"]))
    for (game_map, side), rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        s = summarize(rs)
        n, rate = s["rounds"], s["first_team_death"] or 0
        if n >= 8 and rate >= 0.27:
            flagged_sides.add(side)
            found.append(Insight(
                "flojo", t("Posicionamiento"),
                t('Morís primero en el {0} de tus rondas de {1} en {2}').format(pct(rate), side, map_label(game_map)),
                t('Fuiste la primera baja de tu equipo en {0} de {1} rondas. Lo esperable es cerca del 20 % (uno de cada cinco).').format(s['first_team_deaths'], n),
                ADVICE_FIRST_DEATH[side], (rate - 0.2) * 10 * _weight(n, 40) + 1, n))
    for side, rs in by_key(rounds, lambda r: r["side"]).items():
        s = summarize(rs)
        if side not in flagged_sides and s["rounds"] >= 12 and (s["first_team_death"] or 0) >= 0.27:
            found.append(Insight(
                "flojo", t("Posicionamiento"), t('Morís primero en el {0} de tus rondas de {1}').format(pct(s['first_team_death']), side),
                t('Fuiste la primera baja de tu equipo en {0} de {1} rondas de {2}. Lo esperable es cerca del 20 %.').format(s['first_team_deaths'], s['rounds'], side), ADVICE_FIRST_DEATH[side],
                (s["first_team_death"] - 0.2) * 10 * _weight(s["rounds"], 40) + 1, s["rounds"]))

    # 2. Primeros duelos de la ronda.
    duels = total["opening_duels"]
    if duels >= 6:
        rate = total["opening_win"] or 0
        detail = (t('De los {0} primeros duelos de ronda en los que participaste, ganaste {1} y perdiste {2}.').format(duels, total['opening_kills'], total['opening_deaths']))
        if rate <= 0.42:
            found.append(Insight("flojo", t("Duelos"), t('Ganás solo el {0} de tus primeros duelos').format(pct(rate)),
                                 detail + t(" Perder la primera pelea deja a tu equipo jugando 4 contra 5."),
                                 [t("Antes de asomar, dejá la mira apuntando a la altura de la cabeza en el ángulo donde va a aparecer."),
                                  t("Asomá en corto (jiggle) para sacar información sin regalar el duelo completo."),
                                  t("Si vas a pelear primero, que sea con una flash propia o de un compañero.")],
                                 (0.5 - rate) * 12 * _weight(duels, 20) + 1, duels, "duelos"))
        elif rate >= 0.6:
            found.append(Insight("fuerte", t("Duelos"), t('Ganás el {0} de tus primeros duelos').format(pct(rate)), detail,
                                 [t("Aprovechalo: pedí ser el que abre en las tomas, con flash de un compañero detrás.")],
                                 (rate - 0.5) * 10 * _weight(duels, 20), duels, "duelos"))

    # 3. Muertes que nadie venga.
    tradeable = total["tradeable_deaths"]
    if tradeable >= 8 and (total["traded"] or 0) <= 0.2:
        found.append(Insight(
            "flojo", t("Posicionamiento"), t('Tu equipo venga solo el {0} de tus muertes').format(pct(total['traded'] or 0)),
            t('De {0} muertes con compañeros vivos, tu equipo mató a tu asesino en menos de 5 segundos solo {1} veces. Estás muriendo lejos de tu equipo.').format(tradeable, tradeable - total['untraded_deaths']),
            [t("Jugá a una distancia en la que un compañero pueda ver a quien te mate."),
             t("Antes de moverte solo, avisá adónde vas para que alguien te siga o te cubra."),
             t("Si estás solo en un sector, jugá para sacar información y retrocedé en vez de pelear.")],
            (0.3 - (total["traded"] or 0)) * 10 * _weight(tradeable, 25) + 1, tradeable, "muertes"))

    # 4. Muertes tempranas por lado.
    for side, rs in by_key(rounds, lambda r: r["side"]).items():
        s = summarize(rs)
        if s["rounds"] >= 10:
            rate = s["early_deaths"] / s["rounds"]
            if rate >= 0.22:
                found.append(Insight(
                    "flojo", t("Posicionamiento"), t('En el {0} de tus rondas de {1} morís en los primeros 25 segundos').format(pct(rate), side),
                    t('Te pasó en {0} de {1} rondas. Morir tan temprano te saca de la ronda antes de que tu equipo pueda usar la información.').format(s['early_deaths'], s['rounds']),
                    [t("Usá el arranque de la ronda para tomar posición, no para buscar la kill."),
                     t("Pedí información (sonido, utilidad del rival) antes de cruzar o asomar a un ángulo abierto.")],
                    (rate - 0.15) * 10 * _weight(s["rounds"], 40) + 0.5, s["rounds"]))

    # 5. Puntería: HS con rifles y pistolas (los francotiradores bajan el promedio).
    gun_kills = gun_hs = 0
    shots: dict[str, list[int]] = {}
    for m in matches:
        for gun, w in m["weapons"].items():
            if gun not in SNIPERS and not gun.startswith("knife") and gun not in ("hegrenade", "inferno", "world"):
                gun_kills += w["kills"]
                gun_hs += w["hs"]
            entry = shots.setdefault(gun, [0, 0])
            entry[0] += w["shots"]
            entry[1] += w["hits"]
    if gun_kills >= 15:
        rate = gun_hs / gun_kills
        if rate < 0.35:
            found.append(Insight("flojo", t("Puntería"), t('Solo el {0} de tus kills con rifles y pistolas son a la cabeza').format(pct(rate)),
                                 t('{0} de {1} kills (sin contar AWP ni Scout).').format(gun_hs, gun_kills),
                                 [t("Caminá con la mira siempre a la altura de la cabeza, pegada a la esquina por donde puede salir alguien."),
                                  t("Hacé 10 minutos de Deathmatch apuntando solo a la cabeza antes de jugar.")],
                                 (0.45 - rate) * 10 * _weight(gun_kills, 60) + 0.5, gun_kills, "kills"))
        elif rate >= 0.55:
            found.append(Insight("fuerte", t("Puntería"), t('El {0} de tus kills con rifles y pistolas son a la cabeza').format(pct(rate)),
                                 t('{0} de {1} kills. Tu ubicación de mira es muy buena.').format(gun_hs, gun_kills), [],
                                 (rate - 0.45) * 8 * _weight(gun_kills, 60), gun_kills, "kills"))
    for gun in sorted(RIFLES, key=lambda g: -shots.get(g, [0, 0])[0]):
        fired, hits = shots.get(gun, [0, 0])
        if fired >= 100 and hits / fired < 0.15:
            found.append(Insight("flojo", t("Puntería"), t('Con la {0} acertás el {1} de tus balas').format(weapon_label(gun), pct(hits / fired)),
                                 t('{0} impactos en {1} disparos. Mucha bala se pierde en ráfagas largas o disparando en movimiento.').format(hits, fired),
                                 [t("Frená antes de disparar (contra-strafe) y tirá ráfagas cortas de 3 a 5 balas."),
                                  t("Practicá el control del retroceso en un mapa de entrenamiento 5 minutos por día.")],
                                 (0.2 - hits / fired) * 10 * _weight(fired, 300) + 0.5, fired, "balas"))
            break

    # 6. Daño por lado y daño general.
    sides = {side: summarize(rs) for side, rs in by_key(rounds, lambda r: r["side"]).items()}
    if all(side in sides and sides[side]["rounds"] >= 10 for side in (t("CT"), "T")):
        weak, strong = sorted((t("CT"), "T"), key=lambda side: sides[side]["adr"])
        gap = sides[strong]["adr"] - sides[weak]["adr"]
        if gap >= 20:
            found.append(Insight("flojo", t("Lados"), t('Tu ADR de {0} ({1:.0f}) está {2:.0f} puntos abajo del de {3}').format(weak, sides[weak]['adr'], gap, strong),
                                 t('{0} rondas de {1} contra {2} de {3}.').format(sides[weak]['rounds'], weak, sides[strong]['rounds'], strong),
                                 [t('Revisá una demo tuya mirando solo las rondas de {0}: dónde te ubicás y cuándo peleás.').format(weak),
                                  t("Copiá la posición o la ejecución de un jugador profesional en ese lado del mapa que más jugás.")],
                                 gap / 10 * _weight(min(sides["CT"]["rounds"], sides["T"]["rounds"]), 40), total["rounds"]))
    if total["rounds"] >= 20 and total["adr"] is not None:
        if total["adr"] >= 90:
            found.append(Insight("fuerte", t("Impacto"), t('Hacés {0:.0f} de daño por ronda').format(total['adr']),
                                 t("Arriba de 80 ya es muy buen nivel en partidas de 5 contra 5."), [],
                                 (total["adr"] - 80) / 10 * _weight(total["rounds"], 60), total["rounds"]))
        elif total["adr"] < 60:
            found.append(Insight("flojo", t("Impacto"), t('Hacés {0:.0f} de daño por ronda').format(total['adr']),
                                 t("Un jugador promedio anda por 70 a 80."),
                                 [t("Aunque no consigas la kill, buscá dejar daño: tirá la HE al grupo y no te quedes sin disparar en los duelos."),
                                  t("Si estás sin información, rotá antes para llegar a los duelos que deciden la ronda.")],
                                 (75 - total["adr"]) / 10 * _weight(total["rounds"], 60), total["rounds"]))

    # 7. Utilidad.
    flashes = total["flashes"]
    if total["rounds"] >= 15 and (total["flashes_per_round"] or 0) < 0.35:
        found.append(Insight("flojo", t("Utilidad"), t('Tirás {0} flashes cada 10 rondas').format(num(total['flashes_per_round'] * 10)),
                             t('{0} flashes en {1} rondas. La flash es la granada más barata y la que más duelos gana.').format(flashes, total['rounds']),
                             [t("Comprá al menos una flash en cada ronda que tengas plata."),
                              t("Aprendé dos flashes para tu sector de CT y dos para entrar de T en tu mapa más jugado.")],
                             (0.5 - total["flashes_per_round"]) * 6 * _weight(total["rounds"], 60) + 0.5, total["rounds"]))
    if flashes >= 10:
        blinded = total["blinded_per_flash"] or 0
        if blinded < 0.5:
            found.append(Insight("flojo", t("Utilidad"), t('Tus flashes ciegan a {0} enemigos en promedio').format(num(blinded, 2)),
                                 t('{0} enemigos cegados más de 0,7 s con {1} flashes.').format(total['enemies_flashed'], flashes),
                                 [t("Tirá las flashes por arriba o con rebote para que exploten apenas pasan la esquina (pop flash)."),
                                  t("Flasheá para el compañero que va a asomar, no para vos después de que el rival ya te vio.")],
                                 (0.8 - blinded) * 5 * _weight(flashes, 30) + 0.5, flashes, "flashes"))
        elif blinded >= 1.0:
            found.append(Insight("fuerte", t("Utilidad"), t('Tus flashes ciegan a {0} enemigos en promedio').format(num(blinded, 2)),
                                 t('{0} enemigos cegados con {1} flashes.').format(total['enemies_flashed'], flashes), [],
                                 (blinded - 0.8) * 4 * _weight(flashes, 30), flashes, "flashes"))
        team_rate = total["team_flashed"] / flashes
        if team_rate >= 0.25:
            found.append(Insight("flojo", t("Utilidad"), t('Cegaste a un compañero {0} veces con {1} flashes').format(total['team_flashed'], flashes),
                                 t("Una flash que ciega a tu equipo regala el duelo que querías ganar."),
                                 [t("Avisá \"flash\" antes de tirarla y tirala hacia donde no mira tu compañero."),
                                  t("Si tu compañero ya está asomado, mejor guardala.")],
                                 team_rate * 6 * _weight(flashes, 30) + 0.3, flashes, "flashes"))
    damaging = total["hes"] + total["molotovs"]
    if damaging >= 8 and (total["util_adr"] or 0) < 3:
        found.append(Insight("flojo", t("Utilidad"), t('Tus granadas hacen {0} de daño por ronda').format(num(total['util_adr'])),
                             t('{0:.0f} de daño con {1} HE y {2} molotovs.').format(total['util_damage'], total['hes'], total['molotovs']),
                             [t("Usá la molotov para sacar a alguien de un rincón fijo o para frenar una entrada, no al aire."),
                              t("Tirá la HE donde se juntan los rivales: después de una flash propia o al escuchar una entrada.")],
                             (5 - (total["util_adr"] or 0)) / 2 * _weight(damaging, 30) + 0.3, damaging, "kills"))

    # 8. Economía.
    by_buy = by_key(rounds, lambda r: r["team_buy"])
    full = summarize(by_buy.get("completa", []))
    if full["rounds"] >= 8 and (full["win_rate"] or 0) < 0.5:
        found.append(Insight("flojo", t("Economía"), t('Con compra completa tu equipo gana solo el {0} de las rondas').format(pct(full['win_rate'])),
                             t('{0} de {1} rondas con todo comprado. Son las rondas que hay que ganar.').format(full['won'], full['rounds']),
                             [t("En rondas de compra completa jugá con tu equipo y usá toda la utilidad: no mueras con granadas en el bolsillo."),
                              t("Si sos el que tiene más plata, tirale un arma al que no llega.")],
                             (0.6 - full["win_rate"]) * 8 * _weight(full["rounds"], 40) + 0.5, full["rounds"]))
    lone = [r for r in rounds if r["buy"] == "completa" and r["team_buy"] in ("ahorro", "forzada") and r["team_equip"] < 2500]
    if len(lone) >= 3:
        found.append(Insight("flojo", t("Economía"), t('En {0} rondas compraste todo mientras tu equipo ahorraba').format(len(lone)),
                             t('Ganaste {0} de esas {1}. Comprar desparejo deja a tu equipo sin plata para la próxima.').format(sum(1 for r in lone if r['won']), len(lone)),
                             [t("Mirá la plata de tu equipo al arrancar la ronda y comprá igual que ellos."),
                              t("Si te sobra, en vez de comprarte todo tirale un arma a un compañero.")],
                             len(lone) / max(1, total["rounds"]) * 20, len(lone)))
    pistol = summarize(by_buy.get("pistola", []))
    if pistol["rounds"] >= 4:
        rate = pistol["win_rate"] or 0
        if rate <= 0.34 or rate >= 0.66:
            found.append(Insight("flojo" if rate <= 0.34 else "fuerte", t("Economía"),
                                 t('Ganás el {0} de las rondas de pistola').format(pct(rate)),
                                 t('{0} de {1}. Tu daño en esas rondas: {2:.0f} por ronda.').format(pistol['won'], pistol['rounds'], pistol['adr']),
                                 [t("En pistola de T, entren juntos a un mismo sitio; en CT, jueguen de a dos y con kevlar.")] if rate <= 0.34 else [],
                                 abs(rate - 0.5) * 6 * _weight(pistol["rounds"], 12), pistol["rounds"]))

    # 9. Clutches.
    clutch_rounds = [r for r in rounds if r["clutch_vs"] and r["clutch_vs"] <= 2]
    if len(clutch_rounds) >= 5:
        won = sum(1 for r in clutch_rounds if r["clutch_won"])
        rate = won / len(clutch_rounds)
        if rate < 0.2:
            found.append(Insight("flojo", t("Clutch"), t('Ganaste {0} de {1} rondas quedando solo contra 1 o 2').format(won, len(clutch_rounds)),
                                 t("En esas situaciones cada duelo tiene que ser de a uno."),
                                 [t("Usá el tiempo y la bomba: obligá al rival a venir a vos."),
                                  t("Moverte en silencio y aislar los duelos vale más que asomar rápido."),
                                  t("Si no se puede ganar, salvá el arma para la ronda siguiente.")],
                                 (0.3 - rate) * 5 * _weight(len(clutch_rounds), 12) + 0.3, len(clutch_rounds), "clutches"))
        elif rate >= 0.45:
            found.append(Insight("fuerte", t("Clutch"), t('Ganaste {0} de {1} rondas quedando solo contra 1 o 2').format(won, len(clutch_rounds)),
                                 t("Buen temple en el final de las rondas."), [],
                                 (rate - 0.3) * 5 * _weight(len(clutch_rounds), 12), len(clutch_rounds), "clutches"))

    # 10. Mapas.
    per_map = by_key(matches, lambda m: m["map"])
    rated = {mp: summarize([r for m in ms for r in m["rounds"]]) for mp, ms in per_map.items() if len(ms) >= 2}
    if len(rated) >= 2:
        worst = min(rated, key=lambda mp: rated[mp]["rating"])
        best = max(rated, key=lambda mp: rated[mp]["rating"])
        if total["rating"] - rated[worst]["rating"] >= 0.12:
            ms = per_map[worst]
            wins = sum(1 for m in ms if m["result"] == "W")
            found.append(Insight("flojo", t("Mapas"), t('{0} es tu peor mapa: rating {1}').format(map_label(worst), num(rated[worst]['rating'], 2)),
                                 t('Tu rating general es {0}. En {1} ganaste {2} de {3} partidas.').format(num(total['rating'], 2), map_label(worst), wins, len(ms)),
                                 [t('Antes de jugar {0}, mirá una demo profesional en ese mapa y elegí una posición para cada lado.').format(map_label(worst)),
                                  t("Si es Premier, considerá vetarlo hasta que lo practiques.")],
                                 (total["rating"] - rated[worst]["rating"]) * 8 * _weight(len(ms), 6), len(ms), "partidas"))
        if rated[best]["rating"] - total["rating"] >= 0.12:
            found.append(Insight("fuerte", t("Mapas"), t('{0} es tu mejor mapa: rating {1}').format(map_label(best), num(rated[best]['rating'], 2)),
                                 t('Contra {0} de tu promedio.').format(num(total['rating'], 2)), [],
                                 (rated[best]["rating"] - total["rating"]) * 6, len(per_map[best]), "partidas"))

    # 11. Tendencia.
    if len(matches) >= 6:
        recent = summarize([r for m in matches[-3:] for r in m["rounds"]])
        before = summarize([r for m in matches[:-3] for r in m["rounds"]])
        gap = recent["rating"] - before["rating"]
        if gap <= -0.15:
            found.append(Insight("flojo", t("Tendencia"), t('Tus últimas 3 partidas vienen con rating {0}').format(num(recent['rating'], 2)),
                                 t('Tu promedio anterior era {0}.').format(num(before['rating'], 2)),
                                 [t("Jugá menos partidas seguidas y calentá 10 minutos antes de entrar."),
                                  t("Revisá la demo de la última derrota buscando dos errores repetidos.")],
                                 abs(gap) * 6, 3, "partidas"))
        elif gap >= 0.15:
            found.append(Insight("fuerte", t("Tendencia"), t('Venís en subida: rating {0} en las últimas 3').format(num(recent['rating'], 2)),
                                 t('Tu promedio anterior era {0}.').format(num(before['rating'], 2)), [], gap * 6, 3, "partidas"))

    # 12. Supervivencia y aporte.
    if total["rounds"] >= 20 and (total["kast"] or 0) >= 0.74:
        found.append(Insight("fuerte", t("Impacto"), t('Aportás en el {0} de las rondas (KAST)').format(pct(total['kast'])),
                             t("Matás, asistís, sobrevivís o te vengan en casi todas las rondas."), [],
                             (total["kast"] - 0.68) * 10 * _weight(total["rounds"], 60), total["rounds"]))

    for item in found:
        item.matches = len(matches)
        item.score *= {"alta": 1.0, "media": 0.85, "baja": 0.6}[item.confidence]
    return sorted(found, key=lambda i: (i.kind != "flojo", -i.score))
