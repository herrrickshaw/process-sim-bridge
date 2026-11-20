import json, os, unittest
from hysys_bridge import mcp_server as M

LIB = os.path.expanduser("~/.graphify/gh-clones/refinery-design-opensource")
try: import numpy; HAVE = os.path.isdir(LIB)
except ImportError: HAVE = False


def call(tool, **args):
    r = M.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})["result"]
    t = r["content"][0]["text"]; return r["isError"], (t if r["isError"] else json.loads(t))


class Refinery(unittest.TestCase):
    def test_registered_and_needs_operator_path(self):
        names = {t["name"] for t in M.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]}
        self.assertTrue({"refinery_crudes", "refinery_run"} <= names)
        os.environ.pop("REFINERY_DESIGN_PATH", None)
        err, msg = call("refinery_run", slate={"x": 1}, throughput_bpd=1000); self.assertTrue(err); self.assertIn("REFINERY_DESIGN_PATH", msg)

    @unittest.skipUnless(HAVE, "needs numpy and the refinery-design-opensource clone")
    def test_run_matches_library_and_closes_mass(self):
        os.environ["REFINERY_DESIGN_PATH"] = LIB
        try:
            err, r = call("refinery_crudes"); self.assertFalse(err); key = r["crudes"][0]["key"]
            err, r = call("refinery_run", slate={key: 1.0}, throughput_bpd=200000); self.assertFalse(err, r)
            self.assertAlmostEqual(r["mass_closure"], 1.0, delta=0.03)
            from refinery_design.assay import load_crude; from refinery_design.flowsheet import refine
            self.assertAlmostEqual(r["light_product_yield_wt_pct"], refine(load_crude(key), 200000).light_product_yield_wt_pct)
            err, msg = call("refinery_run", slate={"nope": 1.0}, throughput_bpd=1000); self.assertTrue(err)
            err, msg = call("refinery_run", slate={key: -1.0}, throughput_bpd=1000); self.assertTrue(err)
            err, r2 = call("refinery_run", slate={key: 1.0}, throughput_bpd=200000, fcc=False, coker=False)
            self.assertGreater(r2["black_oil_yield_wt_pct"], r["black_oil_yield_wt_pct"])
        finally: os.environ.pop("REFINERY_DESIGN_PATH", None)

    @unittest.skipUnless(HAVE, "needs numpy and the refinery-design-opensource clone")
    def test_pool_becomes_a_buildable_session(self):
        from hysys_bridge.dwsim import tools as DT
        os.environ["REFINERY_DESIGN_PATH"] = LIB; M.SESSIONS.clear(); DT.CASES.clear()
        try:
            slate = {"azeri_btc": 1.0}
            err, r = call("refinery_to_session", name="g", slate=slate, throughput_bpd=200000, pool="gasoline_range", heat_to_C=120)
            self.assertFalse(err, r); self.assertAlmostEqual(M.SESSIONS["g"].streams["FEED"].mass_flow_kg_h, r["pool_kg_h"])
            self.assertAlmostEqual(sum(r["surrogate_mass_fractions"].values()), 1.0)
            err, b = call("dwsim_build", name="g", confirm=True); self.assertTrue(b["built"], b)
            err, e = call("refinery_to_session", name="g", slate=slate, throughput_bpd=200000, pool="gasoline_range", heat_to_C=120); self.assertTrue(err); self.assertIn("overwrite", e)
            err, e = call("refinery_to_session", name="h", slate=slate, throughput_bpd=200000, pool="petcoke", heat_to_C=120); self.assertTrue(err); self.assertIn("surrogate", e)
        finally: os.environ.pop("REFINERY_DESIGN_PATH", None)


if __name__ == "__main__":
    unittest.main()
