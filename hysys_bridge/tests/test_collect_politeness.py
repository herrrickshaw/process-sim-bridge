"""robots.txt failures and redirects. Everything runs against two servers on this machine."""
import http.server, json, os, tempfile, threading, unittest, urllib.error
from unittest import mock

from hysys_bridge.casebook import collect

PAGE = b"<html><title>DWSIM notes</title><body>DWSIM heater tutorial exercise.</body></html>"


def server():
    class H(http.server.BaseHTTPRequestHandler):
        hits, redirects, statuses, bodies = [], {}, {}, {}
        redirect_code = 302
        def log_message(self, *a): pass
        def do_GET(self):
            cls = type(self); cls.hits.append(self.path)
            if self.path in cls.redirects:
                self.send_response(cls.redirect_code); self.send_header("Location", cls.redirects[self.path]); self.end_headers(); return
            if self.path in cls.statuses: self.send_response(cls.statuses[self.path]); self.end_headers(); return
            body = cls.bodies.get(self.path)
            if body is None and self.path == "/robots.txt": self.send_response(404); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.end_headers(); self.wfile.write(body or PAGE)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, H


class Base(unittest.TestCase):
    def setUp(self):
        (self.a_srv, self.A), (self.b_srv, self.B) = server(), server()
        for s in (self.a_srv, self.b_srv): self.addCleanup(s.server_close); self.addCleanup(s.shutdown)
        self.a = f"http://127.0.0.1:{self.a_srv.server_address[1]}"
        self.b = f"http://localhost:{self.b_srv.server_address[1]}"     # a different host name as far as the collector can tell

    def run_urls(self, *urls):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "g.jsonl"); self.sleeps = []
            rows = collect.run(list(urls), out, robots=collect.Robots(), sleep=self.sleeps.append)
            with open(out) as fh: self.raw = fh.read()
            return rows

    def public(self):
        """Pretend the test servers are on public addresses, to reach the checks that come after that one."""
        p = mock.patch.object(collect, "_is_public", lambda host: True); p.start(); self.addCleanup(p.stop)


class RobotsFailures(Base):
    def test_only_a_missing_robots_file_means_allowed(self):
        for code in (400, 401, 403, 405, 429, 451, 500, 502, 503):
            with self.subTest(code=code):
                self.A.hits.clear(); self.A.statuses["/robots.txt"] = code
                row = self.run_urls(self.a + "/page")[0]
                self.assertEqual(row["status"], "skipped-robots", row)
                self.assertNotIn("/page", self.A.hits)
        for code in (404, 410):
            with self.subTest(code=code):
                self.A.statuses["/robots.txt"] = code
                self.assertEqual(self.run_urls(self.a + "/page")[0]["status"], "ok")

    def test_a_challenge_page_served_as_robots_txt_is_not_permission(self):
        self.A.bodies["/robots.txt"] = b"<html><title>Just a moment...</title>Verify you are human captcha</html>"
        self.assertEqual(self.run_urls(self.a + "/page")[0]["status"], "skipped-robots")
        self.assertNotIn("/page", self.A.hits)

    def test_robots_redirected_to_a_local_address_on_another_host_is_refused(self):
        self.A.redirects["/robots.txt"] = self.b + "/robots.txt"
        self.assertEqual(self.run_urls(self.a + "/page")[0]["status"], "skipped-robots")
        self.assertEqual((self.B.hits, "/page" in self.A.hits), ([], False))

    def test_robots_redirected_on_the_same_host_is_read(self):
        self.A.redirects["/robots.txt"] = "/real-robots"
        self.A.bodies["/real-robots"] = b"User-agent: *\nDisallow: /page\n"
        self.assertEqual(self.run_urls(self.a + "/page")[0]["status"], "skipped-robots")
        self.assertNotIn("/page", self.A.hits)


class Redirects(Base):
    def test_a_redirect_to_a_local_address_on_another_host_is_not_followed(self):
        self.A.redirects["/go"] = self.b + "/secret"
        row = self.run_urls(self.a + "/go")[0]
        self.assertEqual(row["status"], "skipped-redirect", row)
        self.assertEqual(self.B.hits, [])

    def test_the_target_hosts_robots_rules_apply(self):
        self.public()
        self.A.redirects["/go"] = self.b + "/closed"
        self.B.bodies["/robots.txt"] = b"User-agent: *\nDisallow: /closed\n"
        self.assertEqual(self.run_urls(self.a + "/go")[0]["status"], "skipped-robots")
        self.assertNotIn("/closed", self.B.hits)

    def test_the_same_hosts_rules_apply_to_the_new_path(self):
        self.A.bodies["/robots.txt"] = b"User-agent: *\nDisallow: /private\n"
        self.A.redirects["/go"] = "/private/x"
        self.assertEqual(self.run_urls(self.a + "/go")[0]["status"], "skipped-robots")
        self.assertNotIn("/private/x", self.A.hits)

    def test_each_hop_waits_for_its_host(self):
        self.A.redirects["/go"] = "/page"
        self.assertEqual(self.run_urls(self.a + "/go")[0]["status"], "ok")
        self.assertTrue(self.sleeps and max(self.sleeps) >= 0.9, self.sleeps)

    def test_query_text_picked_up_in_a_redirect_is_not_recorded(self):
        self.A.redirects["/go"] = "/page?session=TOKEN123#frag"
        row = self.run_urls(self.a + "/go")[0]
        self.assertEqual((row["status"], row["final_url"]), ("ok", self.a + "/page"))
        self.assertNotIn("TOKEN123", self.raw)

    def test_a_seed_with_a_query_and_no_redirect_is_kept(self):
        self.assertEqual(self.run_urls(self.a + "/page?id=7")[0]["final_url"], self.a + "/page?id=7")

    def test_a_blocked_host_is_not_reached_through_a_redirect(self):
        self.public()
        self.B.statuses["/wall"] = 403
        self.A.redirects["/go"] = self.b + "/other"
        rows = self.run_urls(self.b + "/wall", self.a + "/go")
        self.assertEqual([r["status"] for r in rows], ["blocked", "skipped-host-blocked"])
        self.assertNotIn("/other", self.B.hits)

    def test_a_block_after_a_redirect_closes_the_host_that_blocked(self):
        self.public()
        self.A.redirects["/go"] = self.b + "/wall"; self.B.statuses["/wall"] = 429
        rows = self.run_urls(self.a + "/go", self.b + "/other", self.a + "/page")
        self.assertEqual([r["status"] for r in rows], ["blocked", "skipped-host-blocked", "ok"])
        self.assertNotIn("/other", self.B.hits)

    def test_redirect_loops_and_other_schemes_stop(self):
        self.A.redirects["/loop"] = "/loop"
        self.assertEqual(self.run_urls(self.a + "/loop")[0]["status"], "skipped-redirect")
        self.assertLessEqual(self.A.hits.count("/loop"), collect.MAX_REDIRECTS + 1)
        for target in ("file:///etc/hosts", "ftp://example.invalid/x", "http://user:pw@127.0.0.1/x"):
            with self.subTest(target):
                self.A.redirects["/go"] = target
                self.assertEqual(self.run_urls(self.a + "/go")[0]["status"], "skipped-redirect")
        self.assertNotIn(":pw@", self.raw)

    def test_a_seed_that_is_not_http_is_never_opened(self):
        with tempfile.NamedTemporaryFile("w", suffix=".html") as f:
            f.write("<title>local file</title>"); f.flush()
            row = self.run_urls("file://" + f.name)[0]
        self.assertEqual(row["status"], "error"); self.assertNotIn("local file", json.dumps(row))


class Failures(Base):
    def test_every_redirect_status_is_followed_by_the_checked_path(self):
        self.A.bodies["/robots.txt"] = b"User-agent: *\nDisallow: /private\n"
        for code in collect.REDIRECT_CODES:
            with self.subTest(code=code):
                self.A.hits.clear(); self.A.redirect_code = code
                self.A.redirects.update({"/go": "/page", "/sneak": "/private/x"})
                self.assertEqual([r["status"] for r in self.run_urls(self.a + "/go", self.a + "/sneak")], ["ok", "skipped-robots"])
                self.assertNotIn("/private/x", self.A.hits)

    def test_a_redirect_to_a_malformed_address_is_refused_and_the_run_carries_on(self):
        for target in ("http://[not-an-address", "//[also-bad/x"):
            with self.subTest(target):
                self.A.redirects["/go"] = target
                rows = self.run_urls(self.a + "/go", self.a + "/page")
                self.assertEqual([r["status"] for r in rows], ["skipped-redirect", "ok"], rows)
                self.assertIn("not a valid URL", rows[0]["why"])

    def test_robots_txt_that_redirects_forever_skips_the_site(self):
        self.A.redirects["/robots.txt"] = "/robots.txt"
        self.assertEqual(self.run_urls(self.a + "/page")[0]["status"], "skipped-robots")
        self.assertEqual(self.A.hits, ["/robots.txt"] * (collect.MAX_REDIRECTS + 1))

    def test_a_connection_failure_is_recorded_and_the_next_url_is_still_tried(self):
        def flaky(request, timeout):
            if request.full_url.endswith("/slow"): raise TimeoutError("simulated")
            return collect._open(request, timeout=timeout)
        with tempfile.TemporaryDirectory() as d:
            rows = collect.run([self.a + "/slow", self.a + "/page"], os.path.join(d, "g.jsonl"), robots=collect.Robots(),
                               sleep=lambda s: None, opener=flaky)
        self.assertEqual([r["status"] for r in rows], ["error", "ok"])
        self.assertEqual(rows[0]["why"], "TimeoutError")


class PublicAddress(unittest.TestCase):
    def test_a_name_that_cannot_be_looked_up_is_not_public(self):
        with mock.patch.object(collect.socket, "getaddrinfo", side_effect=OSError("no such host")):
            self.assertFalse(collect._is_public("nowhere.example"))

    def test_loopback_private_and_link_local_are_not_public(self):
        for host in ("127.0.0.1", "localhost", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1"):
            with self.subTest(host):
                self.assertFalse(collect._is_public(host))
        self.assertTrue(collect._is_public("93.184.216.34"))                 # a literal public address: no lookup needed


if __name__ == "__main__":
    unittest.main()
