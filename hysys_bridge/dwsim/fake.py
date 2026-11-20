"""In-process stand-in for the DWSIM MCP server (same Transport interface). It enforces the tool and argument names of the
REAL server as observed 2026-11-20 (dwsim_* underscore names, flowsheet_id on every call but create, `names`,
feed_stream/product_stream, unitop_set properties). No thermodynamics: "solving" propagates specs. It is a plumbing test only;
tests/test_dwsim_live.py runs the same backend against the real server."""
from __future__ import annotations
from .backend import TOOLS

KNOWN = {"Nitrogen", "Hydrogen", "Ammonia", "Water", "Carbon monoxide", "Carbon dioxide", "Ethanol", "Methanol", "Benzene", "Toluene", "Methane", "Propylene", "Propane", "N-butane", "N-pentane", "N-hexane", "N-heptane", "N-octane", "N-decane", "N-dodecane"}  # hydrocarbons verified live 2026-11-20 (Propylene via the cumene heater case)
PACKAGES = {"Raoult's Law", "Peng-Robinson (PR)", "Soave-Redlich-Kwong (SRK)", "NRTL", "Steam Tables (IAPWS-IF97)"}
REQ = {"create": set(), "add_compounds": {"flowsheet_id", "names"}, "set_package": {"flowsheet_id", "name"},
       "add_stream": {"flowsheet_id", "name"}, "add_unitop": {"flowsheet_id", "type", "name"}, "unitop_set": {"flowsheet_id", "name", "properties"},
       "connect": {"flowsheet_id", "unitop"}, "dof": {"flowsheet_id"}, "check": {"flowsheet_id"}, "solve": {"flowsheet_id"},
       "stream_results": {"flowsheet_id", "name"}, "add_conversion": {"flowsheet_id", "name", "stoichiometry", "base_compound"}, "explain": {"flowsheet_id", "object_name"}, "add_equilibrium": {"flowsheet_id", "name", "stoichiometry", "base_compound"}}
OPT = {"create": {"name"}, "add_stream": {"temperature_K", "pressure_Pa", "mass_flow_kg_s", "molar_flow_mol_s", "vapor_fraction", "composition"},
       "connect": {"feed_stream", "feed_port", "product_stream", "product_port"}, "add_conversion": {"conversion", "phase"}, "add_equilibrium": {"phase", "basis", "units", "lnkeq_expression"}}


class FakeDwsim:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.objects: dict[str, dict] = {}
        self.ports: dict[str, dict] = {}
        self.params: dict[str, dict] = {}
        self.compounds: list[str] = []
        self.package = None
        self.solved = False
        self.reactions: dict[str, dict] = {}
        self.duty_kW = -127.495                                              # what the fake server's explanation says; tests change it

    def call(self, tool, args):
        self.calls.append((tool, args))
        n = {v: k for k, v in TOOLS.items()}.get(tool)
        if n is None: raise RuntimeError(f"unknown tool {tool}")
        extra = set(args) - REQ[n] - OPT.get(n, set()) - ({"flowsheet_id"} if n == "create" else set())
        miss = REQ[n] - set(args)
        if miss or extra: raise RuntimeError(f"{tool}: missing {sorted(miss)} unexpected {sorted(extra)}")
        if n == "create": return {"flowsheet_id": "fs-1"}
        if args["flowsheet_id"] != "fs-1": raise RuntimeError("unknown flowsheet_id")
        if n == "add_compounds":
            bad = [c for c in args["names"] if c not in KNOWN]
            if bad: raise RuntimeError(f"compound(s) not in database: {bad}")
            self.compounds = list(args["names"]); return {"added": self.compounds}
        if n == "set_package":
            if args["name"] not in PACKAGES: raise RuntimeError(f"The given key '{args['name']}' was not present in the dictionary.")
            self.package = args["name"]; return {"property_package": self.package}
        if n == "add_equilibrium":
            if args["name"] in self.reactions: raise RuntimeError("Reaction name must be unique in the flowsheet")
            self.reactions[args["name"]] = dict(args, conversion="0"); return {"name": args["name"], "type": "Equilibrium", "reaction_set": "DefaultSet"}
        if n == "add_conversion":
            if args["name"] in self.reactions: raise RuntimeError("Reaction name must be unique in the flowsheet")
            if args["base_compound"] not in args["stoichiometry"]: raise RuntimeError("base compound is not in the stoichiometry")
            self.reactions[args["name"]] = dict(args); return {"name": args["name"], "type": "Conversion", "reaction_set": "DefaultSet"}
        if n == "explain": return {"object": args["object_name"], "lines": ["## What fixes the extent", f"The reactor operates in the mode \"Isothermic\". The outlet temperature is 25 C and the duty is {self.duty_kW} kW."]}
        if n == "add_stream": self.objects[args["name"]] = {"kind": "stream", **args}; return {"stream": args["name"]}
        if n == "add_unitop": self.objects[args["name"]] = {"kind": "unit", **args}; return {"unitop": args["name"]}
        if n == "unitop_set": self.params.setdefault(args["name"], {}).update(args["properties"]); return {"applied": list(args["properties"])}
        if n == "connect":
            for k in ("feed_stream", "product_stream"):
                if k in args:
                    if self.objects.get(args[k], {}).get("kind") != "stream": raise RuntimeError(f"{args[k]} is not a material stream")
                    self.ports.setdefault(args["unitop"], {})[args[k]] = (k, args.get(k.replace("stream", "port"), 0))
            return {"unitop": args["unitop"], "connections": []}
        if n == "dof":
            open_ = []
            for name, o in self.objects.items():
                if o["kind"] == "stream" and not any(name in p for p in self.ports.values() if p.get(name, ("",))[0] == "product_stream"):
                    miss = [k for k in ("temperature_K", "pressure_Pa", "composition") if k not in o] + ([] if {"mass_flow_kg_s", "molar_flow_mol_s"} & set(o) else ["flow"])
                    if miss: open_.append({"object": name, "remaining": len(miss), "missing": miss})
                if o["kind"] == "unit":
                    need = {"Pump": "DeltaP", "Heater": "OutletTemperature", "Cooler": "OutletTemperature"}.get(o["type"])
                    if need and need not in self.params.get(name, {}): open_.append({"object": name, "remaining": 1, "missing": [need]})
            return {"fully_specified": not open_, "remaining": len(open_), "objects": open_}
        if n == "check": return {"ready": True, "blockers": 0, "warnings": 0, "findings": []}
        if n == "solve": self.solved = True; return {"ok": True, "error_count": 0, "errors": [], "note": "fake: specs propagated, nothing calculated"}
        if n == "stream_results":
            o = self.objects[args["name"]]; t = o.get("temperature_K")
            for u, ports in self.ports.items():                               # derived stream: take the unit's spec
                if ports.get(args["name"], ("",))[0] == "product_stream":
                    t = self.params.get(u, {}).get("OutletTemperature", t)
            return {"name": args["name"], "temperature_K": t or 0.0, "pressure_Pa": o.get("pressure_Pa", 0.0),
                    "mass_flow_kg_s": o.get("mass_flow_kg_s", 0.0), "molar_flow_mol_s": 0.0, "phases": []}
