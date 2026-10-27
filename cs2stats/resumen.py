"""El mensaje de Steam que te llega al terminar cada partida: lo mejor que hiciste, en pocas líneas.

Con la demo analizada se buscan los momentos más fuertes (multikills, clutches, récords contra tus partidas anteriores).
Si la demo no llega (por ejemplo en FACEIT), se arma uno más corto con lo que CS2 manda al terminar (GSI).
"""

from __future__ import annotations

from .i18n import language, t
from .metrics import map_label, weapon_label

RECENT = 20     # partidas anteriores contra las que se compara


def _num(value: float, decimals: int = 0) -> str:
    text = f"{value:,.{decimals}f}"
    if language() == "es":
        text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    return text


def _me(match: dict) -> dict | None:
    return next((p for p in match.get("scoreboard") or [] if p.get("me")), None)


def _header(map_name: str, us: int, them: int) -> str:
    if us > them:
        return t("GG! Ganaste {us} a {them} en {map}.", us=us, them=them, map=map_label(map_name))
    if us < them:
        return t("Perdiste {us} a {them} en {map}.", us=us, them=them, map=map_label(map_name))
    return t("Empataste {us} a {them} en {map}.", us=us, them=them, map=map_label(map_name))


def highlights(match: dict, previous: list[dict]) -> list[str]:
    """Los momentos más fuertes de la partida, del mejor al menos bueno."""
    me = _me(match)
    stats = me["stats"] if me else {}
    found: list[tuple[int, str]] = []
    rounds = match.get("rounds") or []
    best = max(rounds, key=lambda r: (r.get("kills") or 0), default=None)
    if best and (best.get("kills") or 0) >= 3:
        kills = best["kills"]
        weapons = [w for w in best.get("kill_weapons") or [] if w]
        weapon = max(set(weapons), key=weapons.count) if weapons else ""
        name = {3: "3K", 4: "4K", 5: "ACE"}.get(kills, f"{kills}K")
        text = (t("{name} en la ronda {n} con {weapon}", name=name, n=best["n"], weapon=weapon_label(weapon)) if weapon
                else t("{name} en la ronda {n}", name=name, n=best["n"]))
        found.append(({3: 60, 4: 85, 5: 100}.get(kills, 100), text))
    for r in rounds:
        if r.get("clutch_won") and r.get("clutch_vs"):
            vs = r["clutch_vs"]
            found.append((40 + 20 * min(vs, 3), t("Clutch 1v{vs} ganado en la ronda {n}", vs=vs, n=r["n"])))
    adr = stats.get("adr") or 0
    past_adr = [(_me(m) or {}).get("stats", {}).get("adr") for m in previous[-RECENT:]]
    past_adr = [a for a in past_adr if a]
    if adr and len(past_adr) >= 5:
        if adr > max(past_adr):
            found.append((75, t("{adr} de ADR: tu mejor en las últimas {n} partidas", adr=_num(adr), n=len(past_adr))))
        elif adr > 1.2 * sum(past_adr) / len(past_adr):
            found.append((45, t("{adr} de ADR, bien arriba de tu promedio ({avg})", adr=_num(adr),
                                avg=_num(sum(past_adr) / len(past_adr)))))
    rating = stats.get("rating") or 0
    allies = [p for p in match.get("scoreboard") or [] if p.get("ally")]
    if me and allies and rating and all(rating >= (p.get("stats") or {}).get("rating", 0) for p in allies):
        found.append((55, t("Fuiste el mejor de tu equipo (rating {rating})", rating=_num(rating, 2))))
    if (stats.get("opening_kills") or 0) >= 4:
        found.append((40, t("Abriste {n} rondas con la primera kill", n=stats["opening_kills"])))
    if (stats.get("kills") or 0) >= 10 and (stats.get("hs") or 0) >= 0.6:
        found.append((35, t("{hs} % de tiros a la cabeza", hs=_num(stats["hs"] * 100))))
    if (stats.get("util_damage") or 0) >= 150:
        found.append((30, t("{dmg} de daño con granadas", dmg=_num(stats["util_damage"]))))
    if (stats.get("enemies_flashed") or 0) >= 10:
        found.append((30, t("Encegueciste {n} rivales con flashes", n=stats["enemies_flashed"])))
    if not found and best and best.get("kills"):
        found.append((10, t("Tu mejor ronda: la {n}, con {k} kills", n=best["n"], k=best["kills"])))
    found.sort(key=lambda item: -item[0])
    return [text for _score, text in found[:4]]


def match_message(match: dict, previous: list[dict]) -> str:
    me = _me(match)
    stats = me["stats"] if me else {}
    lines = [_header(match["map"], match["score_us"], match["score_them"])]
    if match.get("rank_type") == 11 and match.get("rank_new"):
        change = match.get("rank_change") or 0
        lines[0] += " " + t("Premier: {rank} ({sign}{change}).", rank=_num(match["rank_new"]),
                             sign="+" if change >= 0 else "", change=_num(change))
    best = highlights(match, previous)
    if best:
        lines.append(t("Lo mejor de tu partida:"))
        lines += [f"• {text}" for text in best]
    if stats:
        lines.append(t("{k}/{d}/{a} · {adr} ADR · rating {rating}", k=stats.get("kills", 0), d=stats.get("deaths", 0),
                       a=stats.get("assists", 0), adr=_num(stats.get("adr") or 0), rating=_num(stats.get("rating") or 0, 2)))
    return "\n".join(lines)


def gsi_message(data: dict) -> str:
    """Resumen corto con lo que manda CS2 al terminar (sin demo)."""
    lines = [_header(data.get("map") or "", int(data.get("score_us") or 0), int(data.get("score_them") or 0))]
    lines.append(t("{k} kills, {d} muertes, {a} asistencias y {mvp} MVP.", k=data.get("kills", 0), d=data.get("deaths", 0),
                   a=data.get("assists", 0), mvp=data.get("mvps", 0)))
    lines.append(t("Cuando analice la demo vas a ver el detalle en CS2 Stats."))
    return "\n".join(lines)
