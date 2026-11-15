"""The physics behind the gauges, in plain words and real units (docs/PHYSICS.md).

The sim (sim.py) keeps its game units: battery and life support in percent, dose in game mSv. This module explains
them and puts them in real units, from backend/data/physics/physics.json (NASA data fetched at build time by
pipeline/physics_data.py; the app never calls NASA). Nothing here changes the game: it only reads the mission.

  * why(m)         the "Why?" card for each gauge: the physics now in plain words with ONE number (shown and spoken
                   forms, <= 20 words), the formula in plain text, the data source, and the Engineer equation.
  * units(m)       the gauges in real units (W, kWh, K, mSv/h, % state of charge) for Engineer mode.
  * numbers(m)     the debrief's cause -> effect lines with real numbers and their sources.

Every number shown comes from physics.json (with its source) or from the sim's own state.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / "data" / "physics" / "physics.json"
GAUGES = ("power", "battery", "life_support", "dose", "heaters", "shields", "rover")
TITLES = {"power": "Solar power", "battery": "Battery", "life_support": "Life support", "dose": "Radiation dose",
          "heaters": "Heaters", "shields": "Shields", "rover": "Rover and ice"}


@lru_cache(maxsize=None)
def table() -> dict:
    return json.loads(DATA.read_text())


def source(sid: str) -> dict:
    s = table()["sources"][sid]
    return {"title": s["title"], "url": s["url"]}


def val(path: str):
    """A value from physics.json by dotted path ("power.solar_constant_w_m2.value")."""
    cur = table()
    for k in path.split("."):
        cur = cur[k]
    return cur


# ---------------------------------------------------------------- shown and spoken forms
# A line is built from parts: plain strings and (number, unit) pairs. shown() writes "41%", "−178 °C", "0.11 mSv/h";
# spoken() writes "41 percent", "minus 178 degrees Celsius", "0.11 millisieverts an hour" (docs/COPY.md: speak numbers
# with their unit).
SPOKEN_UNIT = {"%": " percent", "°": " degrees", "°C": " degrees Celsius", "K": " kelvin", "mSv/h": " millisieverts an hour",
               "mSv": " millisieverts", "kWh": " kilowatt hours", "kW": " kilowatts", "W": " watts", "h": " hours",
               "x": " times", "kg": " kilograms", "km": " kilometres", "m²": " square metres", "W/m²": " watts per square metre"}
TIGHT = {"%", "°", "x"}


def _num(n: str, spoken: bool) -> str:
    n = str(n)
    if n.startswith(("-", "−")):
        return ("minus " if spoken else "−") + n[1:]
    return n


def shown(parts) -> str:
    out = []
    for p in parts:
        if isinstance(p, tuple):
            n, u = p
            out.append(_num(n, False) + ("" if u in TIGHT else " ") + u if u else _num(n, False))
        else:
            out.append(p)
    return "".join(out)


def spoken(parts) -> str:
    out = []
    for p in parts:
        if isinstance(p, tuple):
            n, u = p
            out.append(_num(n, True) + SPOKEN_UNIT.get(u, (" " + u) if u else ""))
        else:
            out.append(p)
    return re.sub(r"\s*\([^)]*\)", "", "".join(out)).replace("  ", " ").strip()   # sources stay on screen only


def words(s: str) -> int:
    return len(s.split())


def _f(x: float, nd: int = 0) -> str:
    v = round(float(x), nd)
    if nd == 0:
        return str(int(v))
    return f"{v:.{nd}f}"


def c_of_k(k: float) -> float:
    return k - 273.15


# ---------------------------------------------------------------- the outpost model (game % -> real units)
def model() -> dict:
    return table()["outpost_model"]


def kw(pct_per_h: float) -> float:
    """A battery rate in %/h as kW (1 %/h of the battery = battery_kwh / 100 kW)."""
    return pct_per_h * model()["battery_kwh"]["value"] / 100.0


def kwh(pct: float) -> float:
    return pct * model()["battery_kwh"]["value"] / 100.0


def _sim():
    from . import sim
    return sim


def load_share(m, k: str) -> float:
    """The share of the outpost's draw that load `k` takes now (by the sim's own weights)."""
    S = _sim()
    tot = sum(m.loads[x] * S.LOAD_WEIGHT[x] for x in S.LOADS)
    return (m.loads[k] * S.LOAD_WEIGHT[k] / tot) if tot else 0.0


def heater_rated_kw() -> float:
    """The heaters' rated power: their draw at a 20% share of the default budget (100% duty, docs/PHYSICS.md)."""
    S = _sim()
    full = model()["heater_full_duty_share_pct"]["value"]
    return kw(S.BASE_DRAW * full * S.LOAD_WEIGHT["heaters"] / sum(S.DEFAULT_LOADS[k] * S.LOAD_WEIGHT[k] for k in S.LOADS))


def heater_kw(m) -> float:
    return kw(_sim().draw_per_h(m) * load_share(m, "heaters"))


def heater_duty(m) -> float:
    """Heater duty cycle 0..1: the time the heaters are on (their average power over their rated power)."""
    full = model()["heater_full_duty_share_pct"]["value"]
    return max(0.0, min(1.0, m.loads["heaters"] / full))


def array_area_m2() -> float:
    p = val("power")
    peak_w = kw(_sim().SOLAR_GEN) * 1000
    return peak_w / (p["solar_constant_w_m2"]["value"] * p["cell_efficiency"]["value"])


NAV = Path(__file__).resolve().parents[2] / "data" / "sites_physics.json"


@lru_cache(maxsize=None)
def nav_place(site_id: str) -> dict:
    """The landing-site navigator's numbers for a site (data/sites_physics.json: LOLA sunlight, Earth view, slopes,
    the drive to ice; Diviner yearly average and maximum temperature). The one table for what both features show."""
    if not NAV.exists():
        return {}
    return next((p for p in json.loads(NAV.read_text())["places"] if p.get("id") == site_id), {})


@lru_cache(maxsize=None)
def site_phys(site_id: str) -> dict:
    """A site's physics: the navigator's table, plus the Diviner night minimum (physics.json, sampled at the
    navigator's spot). Temperatures in K; slopes are the ice drive's (LOLA), as the navigator shows them."""
    nav, own = nav_place(site_id), table()["sites"].get(site_id, {})
    out: dict = {}
    t = nav.get("temp_c")
    dv = {}
    if t:
        dv["avg_k"] = {"value": t["value"] + 273.15, "source": "diviner_prp"}
        dv["max_k"] = {"value": t["range"][1] + 273.15, "source": "diviner_prp"}
    if (own.get("diviner") or {}).get("min_k"):
        dv["min_k"] = own["diviner"]["min_k"]
    if nav.get("sunlight_pct", {}).get("value") == 0:
        dv["psr"] = True
    if dv:
        out["diviner"] = dv
    d = nav.get("drive_to_ice") or {}
    if d:
        out["slope"] = {"median_deg": {"value": d["mean_slope_deg"], "source": "lola_slope"},
                        "p90_deg": {"value": d["steep_slope_deg"], "source": "lola_slope"}, "km": d.get("km")}
    return out


def outside_k(m, in_sun: bool | None = None) -> float | None:
    """The ground temperature at the outpost (LRO Diviner): the sunlit maximum or the dark minimum."""
    S = _sim()
    env = S.env_at(m, m.t_h)
    lit = env["in_sun"] if in_sun is None else in_sun
    d = site_phys(m.site_id).get("diviner")
    if not d:
        return None
    if d.get("psr"):
        return d["avg_k"]["value"]      # the shadowed floor: its year-round mean (it never gets sunlight)
    return d["max_k"]["value"] if lit else d["min_k"]["value"]


def units(m) -> dict:
    """The gauges in real units (Engineer mode). Pure read of the mission."""
    S = _sim()
    env = S.env_at(m, m.t_h)
    gen = S.SOLAR_GEN * m.array_eff * env["sun_frac"]
    draw = S.draw_per_h(m)
    t_out = outside_k(m)
    return {"battery_kwh": round(kwh(m.power), 1), "battery_capacity_kwh": model()["battery_kwh"]["value"],
            "soc_pct": round(m.power, 1), "solar_kw": round(kw(gen), 2), "backup_kw": round(kw(S.BACKUP_GEN), 2),
            "load_kw": round(kw(draw), 2), "net_kw": round(kw(gen + S.BACKUP_GEN - draw), 2),
            "heater_kw": round(heater_kw(m), 2), "heater_duty_pct": round(heater_duty(m) * 100),
            "heater_rated_kw": round(heater_rated_kw(), 2),
            "outside_k": None if t_out is None else round(t_out), "outside_c": None if t_out is None else round(c_of_k(t_out)),
            "dose_rate_msv_h": round(S.dose_rate(m, m.t_h, env), 3),
            "dose_rate_real_msv_h": round(S.dose_rate(m, m.t_h, env) / S.radiation()["game"]["dose_scale_factor"], 3),
            "lit_pct": round(env["sun_frac"] * m.array_eff * 100), "array_m2": round(array_area_m2())}


# ---------------------------------------------------------------- the "Why?" cards
def _card(g: str, parts, src: str | list, formula: str | None = None, eng: str | None = None, pretend=False) -> dict:
    srcs = [src] if isinstance(src, str) else list(src)
    return {"id": g, "title": TITLES[g], "text": shown(parts), "say": spoken(parts),
            "formula": formula, "eng": eng, "source": source(srcs[0]), "sources": [source(s) for s in srcs],
            "pretend": pretend}


def _power(m, env) -> dict:
    S = _sim()
    s = S.site(m.site_id)
    if s.get("power_from"):
        eff = s["power_from"]["efficiency"]
        return _card("power", ["No Sun reaches the floor. Power comes down a cable from the rim; ", (_f(100 - eff * 100), "%"),
                               " is lost (pretend)."], "lola_illum",
                     "Power here = rim panels × cable efficiency",
                     f"P = P_rim × {eff:g} = {kw(S.SOLAR_GEN * m.array_eff * env['sun_frac']):.1f} kW", pretend=True)
    psun = env["sun_elev_deg"] - S._horizon(m.site_id, "sun", m.t_h)   # the Sun above (or below) the LOLA skyline
    lit = env["sun_frac"] * m.array_eff
    eq = (f"P = {val('power.solar_constant_w_m2.value'):g} W/m² × {array_area_m2():.0f} m² × "
          f"{val('power.cell_efficiency.value') * 100:.0f}% × {lit * 100:.0f}% lit = {kw(S.SOLAR_GEN * lit):.1f} kW")
    formula = "Panel power = sunlight × panel area × cell efficiency"
    if m.array_eff < 1:
        return _card("power", ["Arrays at ", (_f(lit * 100), "%"), ": a micrometeorite hit them. The rover can fix it."],
                     "horizons", formula, eq)
    if env["sun_frac"] <= 0:
        return _card("power", ["No sunlight: the Sun is ", (_f(abs(psun), 1), "°"), " below the skyline (JPL Horizons, LOLA). "
                               "Only the backup runs."], "horizons", formula, eq)
    if env["sun_frac"] < 1:
        return _card("power", ["Panels make ", (_f(lit * 100), "%"), " now: the Sun sits on the skyline, its disk partly "
                               "hidden (JPL Horizons)."], ["horizons", "sunfact"], formula, eq)
    return _card("power", ["Full Sun, just ", (_f(psun, 1), "°"), " above the skyline (JPL Horizons, LOLA). Upright panels "
                           "catch the low Sun."], ["horizons", "vsat"], formula, eq)


def _battery(m, env) -> dict:
    S = _sim()
    gen = S.SOLAR_GEN * m.array_eff * env["sun_frac"] + S.BACKUP_GEN
    draw = S.draw_per_h(m)
    net = gen - draw
    B = model()["battery_kwh"]["value"]
    eq = (f"ΔE = ({kw(gen):.1f} − {kw(draw):.1f}) kW × 1 h = {kw(net):+.1f} kWh; "
          f"SoC = {kwh(m.power):.0f} / {B:g} kWh = {m.power:.0f}%")
    formula = "Battery change = power made − power used, every hour"
    if m.power >= 99.5 and net >= 0:
        parts = ["Battery full: ", (_f(m.power), "%"), ". The panels make more than the outpost uses."]
    elif abs(net) < 0.05:
        parts = ["Battery steady at ", (_f(m.power), "%"), ": power made equals power used."]
    elif net > 0:
        parts = ["Charging: the panels make more than the outpost uses, ", (_f(net, 1), "%"), " an hour."]
    else:
        parts = ["Draining ", (_f(-net, 1), "%"), " an hour: the outpost uses more than the panels make."]
    return _card("battery", parts, ["outpost_model", "li_ion"], formula, eq)


def _life(m, env) -> dict:
    S = _sim()
    L = m.loads
    gain = S.LS_FROM_RECYCLER * (L["life_support"] / 30.0) + S.LS_FROM_GREENHOUSE * (L["greenhouse"] / 15.0) * \
        (0.5 if (m.power_save or m.shelter) else 1.0)
    net = gain - S.LS_USE
    o2 = val("life.o2_kg_per_person_day.value")
    eq = (f"Δair = recycler + greenhouse − crew = {S.LS_FROM_RECYCLER * L['life_support'] / 30:.2f} + "
          f"{gain - S.LS_FROM_RECYCLER * L['life_support'] / 30:.2f} − {S.LS_USE:.2f} = {net:+.2f} %/h; "
          f"one person breathes {o2:g} kg O₂ a day")
    formula = "Air change = recycler + plants − what the crew breathes"
    parts = ["Each person breathes about ", (_f(o2, 1), "kg"), " of oxygen a day (NASA). "
             + ("The recycler keeps up." if net >= 0 else "Air drops unless you add ice or power.")]
    return _card("life_support", parts, "bvad", formula, eq)


def _dose(m, env) -> dict:
    S = _sim()
    g = S.radiation()["game"]
    r = S.dose_rate(m, m.t_h, env)
    st = env["storm"]
    mult = S.storm_multiplier(st.event) if st else 1.0
    shield = g["shields_max_effect"] * min(1.0, m.loads["shields"] / 30.0)
    shelter = (g["shelter_factor_storm"] if st else g["shelter_factor_quiet"]) if m.shelter else 1.0
    eq = (f"rate = {g['game_baseline_msv_per_h']:g} × {mult:g} storm × (1 − {shield:.2f} shields) × {shelter:g} shelter"
          f" = {r:.3f} mSv/h (game doses ×{g['dose_scale_factor']:g})")
    formula = "Dose rate = cosmic rays × storm × shields × shelter"
    if st:
        if m.shelter:
            parts = ["Storm: particles at ", (_f(mult, 0), "x"), " normal. The shelter's packed mass blocks three quarters."]
            return _card("dose", parts, ["donki", "artemis1_shelter"], formula, eq)
        ev = val("radiation.crater_sep_events")[0]
        parts = ["Storm: radiation ", (_f(mult, 0), "x"), " normal here. LRO's CRaTER saw real storms thousands of times "
                 "quiet. Shelter!"]
        return _card("dose", parts, ["donki", "crater_events"], formula,
                     eq + f"; CRaTER {ev['id']}: peak {ev['peak_mgy_per_h']:g} mGy/h vs quiet "
                          f"{val('radiation.crater_quiet_gcr.mgy_per_h.value'):g} mGy/h (thin shielding)")
    crater = val("radiation.crater_quiet_gcr.msv_per_h.value")
    parts = ["Cosmic rays: ", (_f(r, 2), "mSv/h"), " now. The game doubles the real Moon dose (Chang'e 4, LRO CRaTER)."]
    return _card("dose", parts, ["change4", "crater"], formula,
                 eq + f"; real quiet Moon: Chang'e 4 {S.radiation()['baseline']['dose_rate_msv_per_h']:g} mSv/h, "
                      f"CRaTER {val('radiation.crater_quiet_gcr.mgy_per_h.value'):g} mGy/h × Q 4.3 ≈ {crater:g} mSv/h")


def _heaters(m, env) -> dict:
    t = outside_k(m)
    d = site_phys(m.site_id).get("diviner") or {}
    duty = heater_duty(m)
    eq = (f"P_heat = duty × rated = {duty * 100:.0f}% × {heater_rated_kw():.2f} kW = {heater_kw(m):.2f} kW"
          + (f"; outside {t:.0f} K" if t is not None else ""))
    formula = "Heater power = duty cycle × rated power"
    if t is None:
        return _card("heaters", ["Heaters keep the water lines from freezing in the dark."], "diviner", formula, eq)
    if d.get("psr"):
        parts = ["The crater floor never sees the Sun: about ", (_f(c_of_k(t)), "°C"), " all year (LRO Diviner). Heaters never rest."]
    elif env["in_sun"]:
        parts = ["Sunlit ground here reaches about ", (_f(c_of_k(t)), "°C"), " (LRO Diviner). In the dark it gets far colder."]
    else:
        parts = ["Dark ground here drops to about ", (_f(c_of_k(t)), "°C"), " (LRO Diviner). Heaters stop the water freezing."]
    return _card("heaters", parts, "diviner", formula, eq)


def _shields(m, env) -> dict:
    S = _sim()
    g = S.radiation()["game"]
    cut = g["shields_max_effect"] * min(1.0, m.loads["shields"] / 30.0)
    eq = f"cut = {g['shields_max_effect'] * 100:.0f}% × min(1, {m.loads['shields']}/30) = {cut * 100:.0f}% (pretend tech)"
    parts = ["Pretend tech: these cut the dose ", (_f(cut * 100), "%"), ". Real shielding is mass, like water or Moon soil."]
    return _card("shields", parts, ["regolith_shield", "game"], "Dose cut = up to half, at 30% power (game rule)", eq,
                 pretend=True)


def _rover(m, env) -> dict:
    S = _sim()
    s = S.site(m.site_id)
    sp = site_phys(m.site_id)
    w = val("ice.lcross_water_wt_pct.value")
    slope = (sp.get("slope") or {}).get("p90_deg", {}).get("value")
    vmax = val("rover.viper_max_slope_deg.value")
    charge = S.ROVER_POWER
    eq = (f"trip = {charge:g}% × {model()['battery_kwh']['value']:g} kWh = {kwh(charge):.1f} kWh; "
          f"steep drive +{S.site(m.site_id).get('rover_slope_power', 0):g}%, crater-slope route +{S.ROUTES['slope']['power']:g}% "
          f"= +{kwh(S.site(m.site_id).get('rover_slope_power', 0) + S.ROUTES['slope']['power']):.1f} kWh; "
          f"water = {w:g}% of the soil mass; NASA's VIPER is built for slopes up to {vmax:g}°")
    formula = "Water you get = soil dug × its water share"
    if m.rover["busy"] and slope:
        parts = ["The drive to ice has slopes up to about ", (_f(slope), "°"), " (LRO LOLA). Climbing costs battery."]
        return _card("rover", parts, ["lola_slope", "lcross"], formula, eq)
    parts = ["LCROSS found about ", (_f(w, 1), "%"), " water in dark polar crater soil. The rover digs it out."]
    return _card("rover", parts, ["lcross", "lola_slope"], formula, eq)


def why(m) -> dict:
    S = _sim()
    env = S.env_at(m, m.t_h)
    return {"power": _power(m, env), "battery": _battery(m, env), "life_support": _life(m, env),
            "dose": _dose(m, env), "heaters": _heaters(m, env), "shields": _shields(m, env), "rover": _rover(m, env)}


# ---------------------------------------------------------------- the ledger (sim._step_hour fills it)
def account(m, env: dict, gen: float, draw: float, p: float, r: float, r_open: float, power_before: float):
    """One mission hour, booked for the debrief: energy made and used, nights, storms. Read-only for the game."""
    S = _sim()
    L = m.phys
    if not L:
        L.update(solar=0.0, load=0.0, heater=0.0, rover=0.0, nights=[], storms={}, min_power=power_before)
    used = draw * p
    heat = used * load_share(m, "heaters")
    L["solar"] += gen - S.BACKUP_GEN
    L["load"] += used
    L["heater"] += heat
    L["min_power"] = min(L["min_power"], m.power)
    s = S.site(m.site_id)
    if not s.get("power_from"):
        nights = L["nights"]
        if not env["in_sun"]:
            if not nights or nights[-1].get("end_h") is not None:
                nights.append({"start_h": m.t_h - 1, "end_h": None, "heater": 0.0, "load": 0.0,
                               "start_power": power_before, "min_power": m.power, "power_save": m.power_save})
            n = nights[-1]
            n["heater"] += heat
            n["load"] += used
            n["min_power"] = min(n["min_power"], m.power)
            n["power_save"] = n["power_save"] or m.power_save
        elif nights and nights[-1].get("end_h") is None:
            nights[-1]["end_h"] = m.t_h - 1
    st = env["storm"]
    if st:
        b = L["storms"].setdefault(st.event["id"], {"hours": 0, "shelter_h": 0, "dose": 0.0, "dose_open": 0.0,
                                                    "date": st.event["date"], "sep": bool(st.event.get("sep")),
                                                    "mult": S.storm_multiplier(st.event)})
        b["hours"] += 1
        b["shelter_h"] += 1 if m.shelter else 0
        b["dose"] += r
        b["dose_open"] += r_open


MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def day_of(date: str) -> str:
    """"2024-05-10" -> "10 May 2024" (reads well on screen and aloud)."""
    try:
        y, mo, d = (int(x) for x in str(date)[:10].split("-"))
        return f"{d} {MONTHS[mo - 1]} {y}"
    except (ValueError, IndexError):
        return str(date)


def _line(lid: str, parts, src: str, eq: str) -> dict:
    return {"id": lid, "text": shown(parts), "say": spoken(parts), "source": source(src), "eq": eq}


def numbers(m) -> list[dict]:
    """3-5 cause -> effect lines for the debrief (shown and spoken forms), each with its source and, for Engineer,
    its equation. Game doses are in game mSv (the game doubles real doses, radiation.json)."""
    S = _sim()
    g = S.radiation()["game"]
    L = m.phys or {}
    out = []
    storms = [b for b in (L.get("storms") or {}).values() if b["sep"] and b["hours"]]
    if storms:
        b = max(storms, key=lambda x: x["dose_open"])
        when = day_of(b["date"])
        if b["shelter_h"]:
            parts = ["You sheltered for ", (str(b["shelter_h"]), "h"), f" in the {when} storm: dose ",
                     (_f(b["dose"], 1), "mSv"), " instead of ", (_f(b["dose_open"], 1), "mSv"), "."]
        else:
            parts = [f"The {when} storm hit the crew outside: dose ", (_f(b["dose"], 1), "mSv"), ". Sheltered, about ",
                     (_f(b["dose_open"] * g["shelter_factor_storm"], 1), "mSv"), "."]
        out.append(_line("storm", parts, "donki",
                         f"dose = Σ rate × 1 h = {b['dose']:.1f} mSv; unsheltered {b['dose_open']:.1f} mSv; "
                         f"shelter × {g['shelter_factor_storm']:g} on storm dose (game mSv)"))
    nights = [n for n in (L.get("nights") or [])]
    if nights:
        n = max(nights, key=lambda x: (x["end_h"] if x["end_h"] is not None else m.t_h) - x["start_h"])
        hours = (n["end_h"] if n["end_h"] is not None else m.t_h) - n["start_h"]
        if hours >= 1:
            parts = ["Your heaters used ", (_f(kwh(n["heater"]), 1), "kWh"), f" over a {hours}-hour night; "
                     "the battery dipped to ", (_f(n["min_power"]), "%"), "."]
            out.append(_line("night", parts, "horizons",
                             f"E_heat = Σ P_heat × 1 h = {kwh(n['heater']):.1f} kWh of {kwh(n['load']):.1f} kWh used "
                             f"that night; battery {kwh(n['start_power']):.0f} → {kwh(n['min_power']):.0f} kWh"))
    elif S.site(m.site_id).get("power_from") and L.get("heater"):
        t = outside_k(m)
        parts = ["Your heaters used ", (_f(kwh(L["heater"]), 1), "kWh"), " against ground at about ", (_f(c_of_k(t)), "°C"), "."]
        out.append(_line("heat", parts, "diviner", f"E_heat = Σ P_heat × 1 h = {kwh(L['heater']):.1f} kWh; ground {t:.0f} K"))
    if L and kwh(L.get("solar", 0)) < 0.5:   # a mission spent in the dark: the Sun stayed behind the LOLA skyline
        parts = ["Your panels made almost nothing: the Sun stayed behind the skyline. The outpost used ",
                 (_f(kwh(L["load"])), "kWh"), "."]
        out.append(_line("solar", parts, "horizons", f"E_used = Σ P_load × 1 h = {kwh(L['load']):.0f} kWh; panels ≈ 0 kWh"))
    elif L.get("solar"):
        parts = ["Your panels made ", (_f(kwh(L["solar"])), "kWh"), "; the outpost used ", (_f(kwh(L["load"])), "kWh"), "."]
        out.append(_line("solar", parts, "horizons",
                         f"E = Σ {val('power.solar_constant_w_m2.value'):g} W/m² × {array_area_m2():.0f} m² × "
                         f"{val('power.cell_efficiency.value') * 100:.0f}% × lit share × 1 h = {kwh(L['solar']):.0f} kWh"))
    if m.ice_runs:
        w = val("ice.lcross_water_wt_pct.value")
        parts = [f"Ice run{'s' if m.ice_runs > 1 else ''} done. Polar soil is about ", (_f(w, 1), "%"),
                 " water, so 100 kg of soil gives about ", (_f(w, 1), "kg"), "."]
        out.append(_line("ice", parts, "lcross", f"water = soil mass × {w:g}% (LCROSS)"))
    real = m.dose / g["dose_scale_factor"]
    base = S.radiation()["baseline"]["dose_rate_msv_per_h"]
    parts = ["Crew dose ", (_f(m.dose, 1), "mSv"), " in game units: about ", (_f(real, 1), "mSv"), " of real Moon radiation."]
    out.append(_line("dose", parts, "change4",
                     f"real = game ÷ {g['dose_scale_factor']:g} = {real:.1f} mSv; quiet Moon ≈ {base:g} mSv/h × 24 h = "
                     f"{base * 24:.1f} mSv/day"))
    return out[:5]
