import http.server, json, os, tempfile, threading, unittest
from hysys_bridge.casebook import collect

PAGES = {
    "/guide.html": ("text/html", b"<html><head><title>Aspen Plus tutorial</title></head><body>Exercise 1: build a flowsheet with a mixer, a heater and a flash drum in Aspen Plus. Problem 2: add a recycle, tear stream convergence. Solution below. (c) 2020 The Authors. SECRETSENTENCE</body></html>"),
    "/cc.html": ("text/html", b"<html><title>DWSIM notes</title><body>DWSIM heater cooler tutorial. Licensed under Creative Commons.</body></html>"),
    "/wall.html": ("text/html", b"<html><title>Just a moment...</title><body>Verify you are human. captcha</body></html>"),
    "/private/x.html": ("text/html", b"<html><title>closed</title></html>"),
    "/big.pdf": ("application/pdf", b"%PDF-1.4 " + b"0" * 5000),
    "/rejected.html": ("text/html", b"<html><head><title>Request Rejected</title></head><body>The requested URL was rejected. Please consult with your administrator. Your support ID is: 123</body></html>"),
}
ROBOTS = b"User-agent: *\nDisallow: /private/\n"


class H(http.server.BaseHTTPRequestHandler):
    hits = []
    robots = ROBOTS
    def log_message(self, *a): pass
    def do_GET(self):
        H.hits.append(self.path)
        if self.path == "/robots.txt":
            if H.robots is None: self.send_response(404); self.end_headers(); return
            self.send_response(200); self.end_headers(); self.wfile.write(H.robots); return
        if self.path == "/forbidden.html": self.send_response(403); self.end_headers(); return
        if self.path in PAGES:
            ct, body = PAGES[self.path]; self.send_response(200); self.send_header("Content-Type", ct); self.end_headers(); self.wfile.write(body); return
        self.send_response(404); self.end_headers()


class Collect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H); cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown()
    def setUp(self): H.hits.clear(); H.robots = ROBOTS

    def run_seeds(self, paths, **kw):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "g.jsonl"); sleeps = []
            rows = collect.run([self.base + p for p in paths], out, robots=collect.Robots(), sleep=sleeps.append, **kw)
            return rows, sleeps, open(out).read()

    def test_indexes_a_guide_without_storing_its_text(self):
        rows, _, raw = self.run_seeds(["/guide.html"]); r = rows[0]
        self.assertEqual(r["status"], "ok"); self.assertEqual(r["title"], "Aspen Plus tutorial"); self.assertEqual(r["kind"], "html")
        self.assertEqual(r["simulators"]["aspen plus"], 2); self.assertEqual(r["unit_ops"]["mixer"], 1); self.assertEqual(r["unit_ops"]["recycle"], 1); self.assertEqual(r["unit_ops"]["tear stream"], 1)
        self.assertGreaterEqual(r["cues"]["exercise"], 1); self.assertEqual(r["licence_hint"], "copyright-notice")
        self.assertNotIn("SECRETSENTENCE", raw); self.assertNotIn("flowsheet with a mixer", raw)                       # counts and metadata only

    def test_creative_commons_is_noticed(self):
        self.assertEqual(self.run_seeds(["/cc.html"])[0][0]["licence_hint"], "creative-commons-mentioned")

    def test_robots_disallow_is_respected_and_the_page_is_not_requested(self):
        rows, _, _ = self.run_seeds(["/private/x.html"]); self.assertEqual(rows[0]["status"], "skipped-robots"); self.assertNotIn("/private/x.html", H.hits)

    def test_a_rule_written_for_the_assistant_is_respected_too(self):
        H.robots = b"User-agent: Claude-User\nDisallow: /\n"
        rows, _, _ = self.run_seeds(["/guide.html"]); self.assertEqual(rows[0]["status"], "skipped-robots"); self.assertIn("Claude-User", rows[0]["robots"]); self.assertNotIn("/guide.html", H.hits)

    def test_missing_robots_means_allowed_but_a_403_on_robots_does_not(self):
        H.robots = None; self.assertEqual(self.run_seeds(["/guide.html"])[0][0]["status"], "ok")
        rb = collect.Robots(fetch=lambda url: (_ for _ in ()).throw(__import__("urllib.error").error.HTTPError(url, 403, "no", {}, None)))
        self.assertFalse(rb.check(self.base + "/guide.html")[0])

    def test_challenge_page_is_recorded_and_the_host_is_left_alone(self):
        rows, _, _ = self.run_seeds(["/wall.html", "/guide.html", "/cc.html"])
        self.assertEqual([r["status"] for r in rows], ["blocked", "skipped-host-blocked", "skipped-host-blocked"]); self.assertNotIn("/guide.html", H.hits)

    def test_http_403_counts_as_a_block(self):
        rows, _, _ = self.run_seeds(["/forbidden.html", "/guide.html"]); self.assertEqual(rows[0]["status"], "blocked"); self.assertEqual(rows[1]["status"], "skipped-host-blocked")

    def test_oversize_files_are_not_kept(self):
        old = collect.MAX_BYTES; collect.MAX_BYTES = 1000
        try: r = self.run_seeds(["/big.pdf"])[0][0]
        finally: collect.MAX_BYTES = old
        self.assertEqual(r["status"], "too-large"); self.assertNotIn("sha256", r)

    def test_a_small_rejection_page_served_with_200_is_a_block(self):
        rows, _, _ = self.run_seeds(["/rejected.html", "/guide.html"]); self.assertEqual(rows[0]["status"], "blocked"); self.assertEqual(rows[1]["status"], "skipped-host-blocked")

    def test_one_second_between_requests_to_the_same_host(self):
        _, sleeps, _ = self.run_seeds(["/guide.html", "/cc.html"]); self.assertTrue(sleeps, "no wait between two requests to one host"); self.assertGreaterEqual(max(sleeps), 0.9)

    def test_crawl_delay_longer_than_a_second_wins(self):
        H.robots = b"User-agent: *\nCrawl-delay: 7\n"
        _, sleeps, _ = self.run_seeds(["/guide.html", "/cc.html"]); self.assertGreaterEqual(max(sleeps), 6.0)

    def test_already_indexed_urls_are_not_fetched_again(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "g.jsonl"); u = [self.base + "/guide.html"]
            collect.run(u, out, robots=collect.Robots(), sleep=lambda s: None); n = len(H.hits); collect.run(u, out, robots=collect.Robots(), sleep=lambda s: None)
            self.assertEqual(len([h for h in H.hits if h == "/guide.html"]), 1); self.assertEqual(len(open(out).read().splitlines()), 1)

    def test_a_blocked_url_is_not_requested_again(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "g.jsonl"); u = [self.base + "/forbidden.html"]
            collect.run(u, out, robots=collect.Robots(), sleep=lambda s: None); collect.run(u, out, robots=collect.Robots(), sleep=lambda s: None)
            self.assertEqual(H.hits.count("/forbidden.html"), 1)

    def test_max_caps_the_number_of_urls(self):
        rows, _, _ = self.run_seeds(["/guide.html", "/cc.html"], max_urls=1); self.assertEqual(len(rows), 1)

    def test_term_counting_needs_whole_words(self):
        self.assertEqual(collect.count_terms("mixers and a mixer; premixer", ["mixer"]), {"mixer": 1})
        self.assertEqual(collect.count_terms("RadFrac, radfrac.", ["radfrac"]), {"radfrac": 2})


if __name__ == "__main__": unittest.main()
