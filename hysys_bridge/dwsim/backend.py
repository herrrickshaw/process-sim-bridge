"""DWSIM backend: a client for DWSIM's MCP server, implementing the same Backend protocol as HYSYS.

VERIFIED 2026-11-20 against the real server (ghcr.io/danwbr/dwsim-mcp:latest, serverInfo dwsim-mcp-server 1.0.0, run over
`podman run -i --rm --network none ... --stdio`): tools/list (58 tools) and a pump + heater water flowsheet that solved.
  * Tool names use UNDERSCORES (dwsim_stream_add_material), not the dotted names in DWSIM's tutorial pages.
  * Property packages are full names: "Peng-Robinson (PR)", "Soave-Redlich-Kwong (SRK)", "NRTL", "Steam Tables (IAPWS-IF97)".
  * Stream `composition` is MASS fractions. Mole-basis input therefore needs molar masses (`mw`), else it is refused.
  * One dwsim_unitop_connect call per stream; Pump takes `DeltaP` (Pa); Heater/Cooler take CalcMode='OutletTemperature',
    OutletTemperature (K) and DeltaP (Pa) via dwsim_unitop_set. Splitter: OperationMode=StreamMassFlowSpec + StreamFlowSpec (first outlet), verified.
  * dwsim_flowsheet_degrees_of_freedom / dwsim_flowsheet_check exist and are used as a gate before solving;
    dwsim_stream_get_results gives real results, so read-back after solve is genuine (the pre-solve read-back is local).
Units: the server is SI (K, Pa, kg/s). Values are converted here (C->K, kPa->Pa, kg/h->kg/s).
"""
from __future__ import annotations
import json, subprocess
from typing import Protocol

TOOLS = {
    "create": "dwsim_flowsheet_create", "add_compounds": "dwsim_thermo_add_compounds",
    "set_package": "dwsim_thermo_set_property_package", "add_stream": "dwsim_stream_add_material",
    "add_unitop": "dwsim_unitop_add", "unitop_set": "dwsim_unitop_set", "connect": "dwsim_unitop_connect",
    "dof": "dwsim_flowsheet_degrees_of_freedom", "check": "dwsim_flowsheet_check", "solve": "dwsim_solve_run",
    "stream_results": "dwsim_stream_get_results",
}
DWSIM_TYPE = {"mixer": "Mixer", "splitter": "Splitter", "pump": "Pump", "heater": "Heater", "cooler": "Cooler",
              "valve": "Valve", "compressor": "Compressor", "separator": "Vessel"}      # names are in dwsim_unitop_add's list
UNIT_PARAMS_VERIFIED = {"pump", "heater", "cooler", "valve", "compressor", "mixer", "separator", "splitter"}   # splitter: first outlet mass flow -> StreamMassFlowSpec, verified 2026-11-20 (1000 -> 300 + 700 kg/h)
PACKAGE = {"Peng-Robinson": "Peng-Robinson (PR)", "SRK": "Soave-Redlich-Kwong (SRK)", "Steam Tables": "Steam Tables (IAPWS-IF97)"}
KEYMAP = {"T": ("temperature_K", lambda v: v + 273.15, lambda v: v - 273.15),
          "P": ("pressure_Pa", lambda v: v * 1e3, lambda v: v / 1e3),
          "mass": ("mass_flow_kg_s", lambda v: v / 3600, lambda v: v * 3600),
          "mol": ("molar_flow_mol_s", lambda v: v * 1e3 / 3600, lambda v: v * 3600 / 1e3)}


class Transport(Protocol):
    def call(self, tool: str, args: dict) -> dict: ...


class StdioTransport:
    """Newline-delimited JSON-RPC to the DWSIM MCP server, e.g.
    StdioTransport(["podman","run","-i","--rm","--network","none","ghcr.io/danwbr/dwsim-mcp:latest","--stdio"])."""
    def __init__(self, cmd: list[str]):
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self._id = 0
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "hysys-bridge", "version": "0.1"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"); self.p.stdin.flush()

    def _rpc(self, method, params):
        self._id += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}) + "\n"); self.p.stdin.flush()
        line = self.p.stdout.readline()
        if not line: raise RuntimeError("DWSIM MCP server closed the pipe")
        msg = json.loads(line)
        if "error" in msg: raise RuntimeError(msg["error"]["message"])
        return msg["result"]

    def call(self, tool, args):
        r = self._rpc("tools/call", {"name": tool, "arguments": args})
        text = r["content"][0]["text"]
        if r.get("isError"): raise RuntimeError(text)
        try: return json.loads(text)
        except json.JSONDecodeError: return {"text": text}

    def close(self):
        try: self.p.stdin.close()                    # EOF ends the --stdio server and, with --rm, removes the container
        finally:
            try: self.p.wait(timeout=10)
            except subprocess.TimeoutExpired: self.p.terminate(); self.p.wait()
            self.p.stdout.close()


class DwsimBackend:
    readback_is_local = True      # get() before solve reads the local buffer; after solve use read_stream()/check_solution()

    def __init__(self, transport: Transport, mw: dict[str, float] | None = None):
        self.t, self.mw = transport, mw          # mw: g/mol per compound, only needed for mole-basis compositions
        self.fid: str | None = None
        self.comps: list[str] = []
        self.streams: dict[str, dict] = {}       # sid -> buffered SI specs (+ "composition" as MASS fractions)
        self.units: dict[str, dict] = {}
        self.flushed = False
        self.last_solve: dict = {}
        self.last_dof: dict = {}
        self.last_findings: list[dict] = []        # diagnostics from the last check/solve: {code, severity, object, message, fix}

    def _c(self, logical, **args):
        if logical != "create": args = {"flowsheet_id": self.fid, **args}
        return self.t.call(TOOLS[logical], args)

    def new_case(self, name, package, components):
        self.fid = self._c("create", name=name).get("flowsheet_id")
        if not self.fid: raise RuntimeError("dwsim_flowsheet_create returned no flowsheet_id")
        self._c("add_compounds", names=list(components))          # raises on an unknown name: loud failure
        self._c("set_package", name=PACKAGE.get(package, package))
        self.comps = list(components)

    def add_stream(self, sid): self.streams[sid] = {}
    def add_unit(self, uid, utype):
        if utype not in DWSIM_TYPE: raise KeyError(f"no DWSIM type for {utype}")
        self.units[uid] = {"type": utype, "inlets": [], "outlets": []}
    def connect(self, uid, inlets, outlets): self.units[uid].update(inlets=list(inlets), outlets=list(outlets))

    def set(self, sid, prop, value):
        if prop not in KEYMAP: raise KeyError(f"no DWSIM stream argument for {prop!r} (volume flow is not accepted)")
        self.streams[sid][KEYMAP[prop][0]] = KEYMAP[prop][1](value)

    def get(self, sid, prop):
        key, _, inv = KEYMAP[prop]; v = self.streams[sid].get(key)
        return None if v is None else inv(v)

    def set_comp(self, sid, x, basis):
        x = {c: x.get(c, 0.0) for c in self.comps}
        if basis == "mole":
            if not self.mw: raise ValueError("DWSIM takes MASS fractions: pass mw={compound: g/mol} to convert a mole-basis composition")
            m = {c: x[c] * self.mw[c] for c in x}; tot = sum(m.values()); x = {c: v / tot for c, v in m.items()}
        self.streams[sid]["composition"] = x

    def get_comp(self, sid): return dict(self.streams[sid].get("composition", {}))   # mass fractions

    def _unit_params(self, u):
        t, ins, outs = u["type"], u["inlets"], u["outlets"]
        if not (ins and outs): return {}
        i, o = self.streams[ins[0]], self.streams[outs[0]]
        p = {}
        dp = i["pressure_Pa"] - o["pressure_Pa"] if "pressure_Pa" in i and "pressure_Pa" in o else None
        if t == "pump" and dp is not None: p["DeltaP"] = -dp                       # pressure INCREASE
        elif t in ("heater", "cooler"):
            if "temperature_K" in o: p.update(CalcMode="OutletTemperature", OutletTemperature=o["temperature_K"])
            if dp is not None: p["DeltaP"] = dp                                    # pressure DROP
        elif t == "valve" and dp is not None: p["DeltaP"] = dp                      # pressure DROP, verified 2026-11-20 (CH4 50->20 bar, isenthalpic)
        elif t == "compressor" and "pressure_Pa" in o: p["POut"] = o["pressure_Pa"]  # absolute outlet pressure; efficiency left at the 75% default
        elif t == "splitter" and len(outs) > 1 and "mass_flow_kg_s" in o:             # first outlet's mass flow fixes the split; the rest is the balance
            p.update(OperationMode="StreamMassFlowSpec", StreamFlowSpec=o["mass_flow_kg_s"])
        return p

    def flush(self):
        """Feeds get their specs; derived streams are created bare and their specs move onto the unit ops."""
        if self.flushed: return
        made = {o for u in self.units.values() for o in u["outlets"]}
        for sid, spec in self.streams.items():
            self._c("add_stream", name=sid, **({} if sid in made else spec))
        for uid, u in self.units.items():
            self._c("add_unitop", type=DWSIM_TYPE[u["type"]], name=uid)
            for k, s in enumerate(u["inlets"]): self._c("connect", unitop=uid, feed_stream=s, feed_port=k)
            for k, s in enumerate(u["outlets"]): self._c("connect", unitop=uid, product_stream=s, product_port=k)
            params = self._unit_params(u)
            if params: self._c("unitop_set", name=uid, properties=params)
        self.flushed = True

    def solve(self) -> bool:
        """Flush, refuse to solve while any specification is open or the flowsheet check reports a blocker, otherwise solve.
        True only if the server says ok AND the solve reported no blocker finding: the server returns ok=true even for a dangling stream
        (verified 2026-11-20), so `ok` alone is not enough. All findings (blockers, warnings) are kept in last_findings."""
        self.flush(); self.last_findings = []
        self.last_dof = self._c("dof")
        if not self.last_dof.get("fully_specified", False):
            open_ = [f"{o['object']}: {', '.join(o.get('missing', []))}" for o in self.last_dof.get("objects", []) if o.get("remaining")]
            self.last_solve = {"ok": False, "blocked": "degrees of freedom still open", "open": open_}
            return False
        chk = self._c("check"); self.last_findings = list(chk.get("findings", []))
        blockers = [f for f in self.last_findings if f.get("severity") == "blocker"]
        if blockers:
            self.last_solve = {"ok": False, "blocked": "flowsheet check reports blockers", "findings": blockers}
            return False
        self.last_solve = self._c("solve")
        self.last_findings = list(self.last_solve.get("findings", self.last_findings))
        blockers = [f for f in self.last_findings if f.get("severity") == "blocker"]
        if blockers: self.last_solve = {**self.last_solve, "ok": False, "blocked": "solve reported blocker findings", "findings": blockers}
        return bool(self.last_solve.get("ok"))

    def read_stream(self, sid) -> dict:
        """Real results in our units (C, kPa, kg/h, mol/s) plus mass-fraction composition from the overall phase."""
        r = self._c("stream_results", name=sid)
        mix = next((ph for ph in r.get("phases", []) if ph.get("name") == "Mixture"), {})
        return {"T": r["temperature_K"] - 273.15, "P": r["pressure_Pa"] / 1e3, "mass": r["mass_flow_kg_s"] * 3600,
                "mol_s": r["molar_flow_mol_s"], "h_kJ_kg": mix.get("enthalpy_kJ_kg"),
                "vapor_fraction": next((ph.get("fraction") for ph in r.get("phases", []) if ph.get("name") == "Vapor"), None), "mass_fractions": {c: v["mass_fraction"] for c, v in mix.get("compounds", {}).items()}}

    def check_solution(self, rel=1e-4) -> list[str]:
        """After a solve: every buffered feed spec and every derived-stream spec must come back from DWSIM. Returns mismatches."""
        bad = []
        for sid, spec in self.streams.items():
            res = self.read_stream(sid)
            for prop, (key, _, inv) in KEYMAP.items():
                if key in spec and prop in res:
                    want, got = inv(spec[key]), res[prop]
                    if abs(got - want) > rel * max(abs(want), 1.0): bad.append(f"{sid} {prop}: spec {want:.6g}, DWSIM {got:.6g}")
        return bad
