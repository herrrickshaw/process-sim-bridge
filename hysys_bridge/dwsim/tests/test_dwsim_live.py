"""Runs the backend against the REAL DWSIM MCP server in a container (no network). Opt-in:
    DWSIM_MCP_LIVE=1 python3 -m unittest hysys_bridge.dwsim.tests.test_dwsim_live
Needs podman/docker with ghcr.io/danwbr/dwsim-mcp:latest pulled (override the command with DWSIM_MCP_CMD)."""
import os, shlex, unittest
from hysys_bridge import hysys_writer
from hysys_bridge.dwsim.backend import DwsimBackend, StdioTransport
from hysys_bridge.dwsim.tests.test_dwsim import sheet

CMD = shlex.split(os.environ.get("DWSIM_MCP_CMD", "podman run -i --rm --network none ghcr.io/danwbr/dwsim-mcp:latest --stdio"))


@unittest.skipUnless(os.environ.get("DWSIM_MCP_LIVE") == "1", "set DWSIM_MCP_LIVE=1 to run against the real DWSIM MCP server")
class Live(unittest.TestCase):
    def test_pump_heater_solves_and_specs_come_back(self):
        t = StdioTransport(CMD)
        try:
            be = DwsimBackend(t)
            hysys_writer.write(sheet(), be)
            self.assertTrue(be.solve(), be.last_solve)
            self.assertEqual(be.check_solution(), [])
            s3 = be.read_stream("S3")
            self.assertAlmostEqual(s3["T"], 80.0, places=3); self.assertAlmostEqual(s3["P"], 480.0, places=3)
            self.assertAlmostEqual(s3["mass"], 1000.0, places=3)
        finally:
            t.close()


if __name__ == "__main__":
    unittest.main()
