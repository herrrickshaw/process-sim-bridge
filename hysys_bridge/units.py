"""Small explicit unit table. Unknown units raise -> forces a human decision."""
_P = {"kpa": 1.0, "pa": 1e-3, "mpa": 1e3, "bar": 100.0, "barg": None, "bara": 100.0,
      "kg/cm2": 98.0665, "kg/cm2a": 98.0665, "psia": 6.894757, "atm": 101.325}
_M = {"kg/h": 1.0, "t/h": 1000.0, "kg/s": 3600.0, "lb/h": 0.45359237, "kg/hr": 1.0, "tph": 1000.0}
_MOL = {"kmol/h": 1.0, "mol/h": 1e-3, "kmol/hr": 1.0, "lbmol/h": 0.45359237, "kgmol/h": 1.0}
_V = {"m3/h": 1.0, "m3/hr": 1.0, "l/h": 1e-3, "m3/s": 3600.0, "bbl/d": 0.158987 / 24}
_E = {"kj/h": 1.0, "mj/h": 1e3, "kw": 3600.0, "gj/h": 1e6, "kcal/h": 4.1868, "btu/h": 1.055056}
ATM_KPA = 101.325


def _norm(u: str) -> str:
    return u.strip().lower().replace(" ", "").replace("²", "2").replace("³", "3").replace("hr", "h")


def to_celsius(v: float, u: str) -> float:
    u = _norm(u).replace("°", "")
    if u in ("c", "degc"): return v
    if u in ("k",): return v - 273.15
    if u in ("f", "degf"): return (v - 32) * 5 / 9
    raise ValueError(f"unknown temperature unit {u!r}")


def to_kpa_abs(v: float, u: str, atm: float = ATM_KPA) -> float:
    k = _norm(u)
    gauge = k.endswith("g") and k not in ("kg",)
    if k in ("barg", "kpag", "kg/cm2g", "psig", "mpag"):
        base = {"barg": 100.0, "kpag": 1.0, "kg/cm2g": 98.0665, "psig": 6.894757, "mpag": 1e3}[k]
        return v * base + atm
    if k == "kpaa": k = "kpa"
    if k not in _P or _P[k] is None:
        raise ValueError(f"unknown/ambiguous pressure unit {u!r} (gauge vs abs must be explicit)")
    return v * _P[k]


def _lin(table, name):
    def f(v, u):
        k = _norm(u)
        if k not in table: raise ValueError(f"unknown {name} unit {u!r}")
        return v * table[k]
    return f

to_kg_h, to_kmol_h, to_m3_h, to_kj_h = (_lin(_M, "mass-flow"), _lin(_MOL, "molar-flow"),
                                        _lin(_V, "vol-flow"), _lin(_E, "energy"))
