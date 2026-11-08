# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 szabiz <szabiz@yahoo.com>
# Copyright (c) 2026 szabiz <szabiz@yahoo.com>
"""
vs_meta.py - a natív VapourSynth-szűrők metaadat-könyvtára (vs_filters/*.json).

A plugin csak a paraméterek nevét és típusát adja meg; az alapértéket, az értelmes tartományt, a címkét és a
súgót nem. Ezeket kézzel összeállított JSON-fájlok tartalmazzák, szűrőnként:

    {"filters": [ {
        "ns": "dfttest", "fn": "DFTTest", "cat": "noise",
        "label": ["Zajszűrő (DFTTest)", "Denoiser (DFTTest)"],      # [magyar, angol] (vagy egy szöveg, vagy {"hu":..,"en":..})
        "help":  ["Rövid leírás", "Short description"],
        "params": [ {"name": "sigma", "type": "float", "default": 8.0, "min": 0, "max": 50, "step": 0.5,
                     "label": [..], "help": [..], "basic": true, "choices": [..]} ],
        "presets": [ {"name": ["Gyenge", "Light"], "values": {"sigma": 4.0}} ] } ]}

type: int / float / bool / str / expr (szabad Python-kifejezés, pl. "[0, 1, 2]").
basic: igaz -> a kártyára azonnal felkerül; a többi a „Paraméter ▾” menüből adható hozzá.
choices: ha meg van adva, legördülő lista lesz a csúszka helyett.

Saját szűrőt a ~/efekt_vs_filters/*.json fájlokba is lehet írni (ez felülírja a beépítettet). Hibás fájl vagy
szűrő kimarad, a többit nem érinti; a hibák listája a load() második visszatérési értéke.
Tiszta logika, nincs benne Tk.
"""
import json
import os
import re

import vs_code

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TYPES = ("int", "float", "bool", "str", "expr")


def loc(v, hu=True):
    """Kétnyelvű szöveg: [hu, en] lista, {"hu":, "en":} szótár vagy sima szöveg."""
    if isinstance(v, dict):
        return str(v.get("hu" if hu else "en") or v.get("en") or v.get("hu") or "")
    if isinstance(v, (list, tuple)):
        if not v:
            return ""
        return str(v[0] if (hu or len(v) < 2) else v[1])
    return "" if v is None else str(v)


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _norm_param(p):
    if not isinstance(p, dict):
        raise ValueError("a paraméter nem szótár")
    name, typ = p.get("name"), p.get("type")
    if not isinstance(name, str) or not _IDENT.match(name):
        raise ValueError("érvénytelen paraméternév: %r" % (name,))
    if typ not in TYPES:
        raise ValueError("%s: ismeretlen típus: %r" % (name, typ))
    if "default" not in p:
        raise ValueError("%s: hiányzik az alapérték" % name)
    d = dict(name=name, type=typ, default=p["default"], lo=_num(p.get("min")), hi=_num(p.get("max")),
             step=_num(p.get("step")), label=p.get("label") or name, help=p.get("help") or "",
             basic=bool(p.get("basic")), choices=None)
    if typ in ("int", "float") and not (isinstance(d["default"], (int, float)) and not isinstance(d["default"], bool)):
        raise ValueError("%s: az alapérték nem szám" % name)
    if typ == "bool" and not isinstance(d["default"], bool):
        raise ValueError("%s: az alapérték nem logikai" % name)
    if p.get("choices") is not None:
        if not isinstance(p["choices"], list) or not p["choices"]:
            raise ValueError("%s: a choices nem üres lista" % name)
        d["choices"] = list(p["choices"])
    if d["step"] is None:
        d["step"] = 1 if typ == "int" else 0.1
    return d


def _norm_filter(f):
    if not isinstance(f, dict):
        raise ValueError("a szűrő nem szótár")
    ns, fn = f.get("ns"), f.get("fn")
    if not (isinstance(ns, str) and isinstance(fn, str) and _IDENT.match(ns) and _IDENT.match(fn)):
        raise ValueError("érvénytelen ns / fn: %r.%r" % (ns, fn))
    params, seen = [], set()
    for p in f.get("params") or []:
        q = _norm_param(p)
        if q["name"] in seen:
            raise ValueError("%s.%s: kétszer szereplő paraméter: %s" % (ns, fn, q["name"]))
        seen.add(q["name"])
        params.append(q)
    presets = []
    for pr in f.get("presets") or []:
        vals = pr.get("values") if isinstance(pr, dict) else None
        if not isinstance(vals, dict) or not vals or any(k not in seen for k in vals):
            raise ValueError("%s.%s: hibás előbeállítás: %r" % (ns, fn, pr.get("name") if isinstance(pr, dict) else pr))
        presets.append(dict(name=pr.get("name") or "?", values=dict(vals)))
    cat = f.get("cat")
    if cat not in vs_code.CAT_KEYS:
        cat = vs_code.guess_cat(fn, ns)
    return dict(ns=ns, fn=fn, key="%s.%s" % (ns, fn), cat=cat, label=f.get("label") or fn, help=f.get("help") or "",
                params=params, presets=presets)


def load(dirs):
    """A megadott mappák *.json fájljaiból {"ns.fn": szűrő}; a későbbi mappa felülírja a korábbit.
    Visszatér: (szótár, [hibaüzenetek])"""
    out, errors = {}, []
    for d in dirs:
        if not d or not os.path.isdir(d):
            continue
        for fname in sorted(os.listdir(d)):
            if not fname.lower().endswith(".json"):
                continue
            path = os.path.join(d, fname)
            try:
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
            except (OSError, ValueError) as e:
                errors.append("%s: %s" % (fname, e))
                continue
            lst = data.get("filters") if isinstance(data, dict) else data
            if not isinstance(lst, list):
                errors.append("%s: nincs 'filters' lista" % fname)
                continue
            for f in lst:
                try:
                    n = _norm_filter(f)
                except (ValueError, TypeError, AttributeError) as e:
                    errors.append("%s: %s" % (fname, e))
                    continue
                out[n["key"]] = n
    return out, errors


# ------------------------------------------------------------------ értékek
def fmt_value(p, value=None):
    """A paraméter értéke (alapból az alapértéke) Python-kifejezésként."""
    v = p["default"] if value is None else value
    t = p["type"]
    if t == "bool":
        return "True" if v else "False"
    if t == "int":
        return str(int(round(float(v))))
    if t == "float":
        return repr(round(float(v), 6))
    if t == "str":
        return repr(str(v))
    return str(v)


def param(meta, name):
    if not meta:
        return None
    return next((p for p in meta["params"] if p["name"] == name), None)


def _same(a, b):
    a, b = str(a).strip(), str(b).strip()
    if a == b:
        return True
    try:
        return abs(float(a) - float(b)) < 1e-9
    except ValueError:
        return False


# ------------------------------------------------------------------ kártyák
def card_from_meta(meta, sig_names=None):
    """Új kártya a szűrő „basic” paramétereivel (alapértékkel). sig_names: a plugin tényleges paraméternevei -
    ha ismertek, a nem létező paraméter kimarad (így a metaadat és a telepített plugin eltérése nem okoz hibát)."""
    kw = [[p["name"], fmt_value(p)] for p in meta["params"]
          if p["basic"] and (sig_names is None or p["name"] in sig_names)]
    return dict(id="code", target="clip", func="core." + meta["key"], pos=["clip"], kw=kw, title=meta["fn"],
                cat=meta["cat"], imports=[])


def known_params(meta, sig_names=None):
    """Az összes (a pluginban is létező) paraméter: [(név, alapérték-kifejezés, címke-objektum), ...]."""
    return [(p["name"], fmt_value(p), p["label"]) for p in meta["params"]
            if sig_names is None or p["name"] in sig_names]


def apply_preset(it, meta, idx):
    """A kártya másolata az idx-edik előbeállítás értékeivel (a többi paraméter marad)."""
    try:
        values = meta["presets"][idx]["values"]
    except (IndexError, KeyError, TypeError):
        return it
    kw = [list(p) for p in (it.get("kw") or [])]
    for name, v in values.items():
        text = fmt_value(param(meta, name), v)
        for p in kw:
            if p[0] == name:
                p[1] = text
                break
        else:
            kw.append([name, text])
    return dict(it, kw=kw)


def preset_match(it, meta):
    """Annak az előbeállításnak az indexe, amelynek minden értéke megegyezik a kártyáéval; különben None."""
    have = {k: v for k, v in (it.get("kw") or [])}
    for i, pr in enumerate(meta.get("presets") or []):
        if all(k in have and _same(have[k], fmt_value(param(meta, k), v)) for k, v in pr["values"].items()):
            return i
    return None
