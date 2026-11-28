"""Polite collector for public university guides and exercises on process simulation (Aspen, HYSYS, DWSIM and others).
It builds an INDEX, not a copy: for each URL it records where the page is, what it is, which simulators and unit operations it mentions, and whether it carries
a licence hint. Page text is never stored (course notes are copyrighted by their authors); keyword counts are computed in memory and thrown away.

Rules it keeps (CLAUDE.md, "Source fetching"): one request per second per host at most (a longer robots.txt crawl-delay wins); robots.txt is checked before every
fetch, for this collector's own agent and for Claude-User, and a site that disallows either is skipped; a captcha, robot check, WAF challenge or login wall ends
work on that host and is recorded, never bypassed; one page per seed URL (no link following); size capped. Seeds come from a file the operator controls.

    python3 -m hysys_bridge.casebook.collect studies/sources/seeds.txt [--out studies/sources/guides.jsonl] [--max 60]
"""
from __future__ import annotations
import datetime, hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser
from html.parser import HTMLParser

AGENT = "process-sim-bridge-collector"
UA = f"{AGENT}/0.1 (index of public teaching material; honours robots.txt)"
ALSO_RESPECT = "Claude-User"                  # robots rules written for the assistant that runs this are honoured too
MAX_BYTES = 25 * 1024 * 1024
MIN_DELAY = 1.0
CHALLENGE = re.compile(r"captcha|cf-chl|just a moment|attention required|are you a robot|verify you are human|access denied|enable javascript and cookies|akamai|sign in to continue|log in to continue|request rejected|requested url was rejected|support id", re.I)
SIMULATORS = ["aspen plus", "aspen hysys", "hysys", "unisim", "dwsim", "pro/ii", "chemcad", "cape-open", "coco", "gproms", "matlab", "python", "excel"]
UNIT_OPS = ["mixer", "splitter", "flash", "heater", "cooler", "heat exchanger", "heatx", "pump", "compressor", "valve", "expander", "radfrac", "distillation", "absorber", "stripper",
            "reactor", "rstoic", "rgibbs", "rplug", "rcstr", "cstr", "pfr", "recycle", "tear stream", "design spec", "sensitivity", "convergence", "adjust"]
CUES = ["exercise", "problem", "homework", "assignment", "tutorial", "laboratory", "lab ", "solution", "case study", "step-by-step", "workshop"]


class _Title(HTMLParser):
    def __init__(self): super().__init__(); self.t, self.on, self.skip = "", False, 0
    def handle_starttag(self, tag, attrs):
        if tag == "title": self.on = True
        if tag in ("script", "style"): self.skip += 1
    def handle_endtag(self, tag):
        if tag == "title": self.on = False
        if tag in ("script", "style"): self.skip = max(0, self.skip - 1)
    def handle_data(self, d):
        if self.on and not self.t: self.t = d.strip()


def count_terms(text: str, terms: list[str]) -> dict[str, int]:
    low = text.lower(); out = {}
    for t in terms:
        n = len(re.findall(r"(?<![a-z0-9])" + re.escape(t) + r"(?![a-z0-9])", low))
        if n: out[t.strip()] = n
    return out


def licence_hint(text: str, html: str = "") -> str:
    if re.search(r"creativecommons\.org|creative commons|cc[- ]by", text + html, re.I): return "creative-commons-mentioned"
    if re.search(r"©|\(c\)\s*\d{4}|copyright", text, re.I): return "copyright-notice"
    return "none-seen"


class Robots:
    """robots.txt per host, fetched once; allowed only if both the collector's agent and Claude-User may fetch the URL."""
    def __init__(self, fetch=None): self.cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}; self.fetch = fetch or self._fetch
    @staticmethod
    def _fetch(url):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=20) as r: return r.status, r.read(512 * 1024).decode("utf-8", "replace")
    def _parser(self, base):
        if base not in self.cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                st, body = self.fetch(base + "/robots.txt"); rp.parse(body.splitlines())
            except urllib.error.HTTPError as e: rp = None if e.code in (404, 410) else "deny" if e.code in (401, 403) else None     # no robots file = allowed; a 401/403 on it = treat as closed
            except Exception: rp = "unreachable"
            self.cache[base] = rp
        return self.cache[base]
    def check(self, url: str) -> tuple[bool, str, float]:
        p = urllib.parse.urlsplit(url); base = f"{p.scheme}://{p.netloc}"; rp = self._parser(base)
        if rp is None: return True, "no robots.txt", 0.0
        if rp == "deny": return False, "robots.txt answered 401/403", 0.0
        if rp == "unreachable": return False, "robots.txt unreachable, not guessing", 0.0
        for agent in (AGENT, ALSO_RESPECT):
            if not rp.can_fetch(agent, url): return False, f"robots.txt disallows {agent}", 0.0
        delay = max(rp.crawl_delay(AGENT) or 0, rp.crawl_delay("*") or 0); return True, "robots.txt allows", float(delay)


def _pdf_facts(data: bytes) -> tuple[str, str, int | None]:
    """(text for in-memory counting, title, pages) via poppler if installed; nothing is kept."""
    if not shutil.which("pdftotext"): return "", "", None
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "a.pdf"); open(f, "wb").write(data)
        text = subprocess.run(["pdftotext", "-q", "-l", "80", f, "-"], capture_output=True, text=True, timeout=120).stdout
        title, pages = "", None
        if shutil.which("pdfinfo"):
            info = subprocess.run(["pdfinfo", f], capture_output=True, text=True, timeout=60).stdout
            m = re.search(r"^Title:\s*(.+)$", info, re.M); title = m.group(1).strip() if m else ""
            m = re.search(r"^Pages:\s*(\d+)", info, re.M); pages = int(m.group(1)) if m else None
    return text, title, pages


def fetch_one(url: str, robots: Robots, opener=None, sleep=time.sleep, last: dict | None = None) -> dict:
    """One row for one URL. `last` maps host -> time of the previous request, for the per-host delay."""
    last = last if last is not None else {}
    row = {"url": url, "host": urllib.parse.urlsplit(url).netloc, "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    ok, why, delay = robots.check(url); row["robots"] = why
    if not ok: row["status"] = "skipped-robots"; return row
    wait = max(MIN_DELAY, delay) - (time.monotonic() - last.get(row["host"], -1e9))
    if wait > 0: sleep(wait)
    last[row["host"]] = time.monotonic()
    safe = urllib.parse.quote(url, safe=":/?&=%#~+@,;")
    req = urllib.request.Request(safe, headers={"User-Agent": UA, "Accept": "text/html,application/pdf;q=0.9,*/*;q=0.1"})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=40) as r:
            row["http"] = r.status; row["final_url"] = r.geturl(); ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower(); row["content_type"] = ctype
            data = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        row["http"] = e.code; row["status"] = "blocked" if e.code in (401, 403, 429, 503) else "error"; row["why"] = f"HTTP {e.code}"; return row
    except Exception as e:
        row["status"] = "error"; row["why"] = f"{type(e).__name__}"; return row
    if len(data) > MAX_BYTES: row["status"] = "too-large"; row["bytes"] = f">{MAX_BYTES}"; return row
    row["bytes"] = len(data); row["sha256"] = hashlib.sha256(data).hexdigest()[:16]
    if ctype == "application/pdf" or data[:5] == b"%PDF-":
        text, title, pages = _pdf_facts(data); html = ""; row.update({"kind": "pdf", "title": title or None, "pages": pages})
    else:
        html = data.decode("utf-8", "replace"); p = _Title(); p.feed(html); text = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html)); row.update({"kind": "html", "title": p.t or None})
        if CHALLENGE.search(html[:6000]) and len(text.strip()) < 2500: row["status"] = "blocked"; row["why"] = "challenge or login wall"; return row
    row["status"] = "ok"; row["licence_hint"] = licence_hint(text, html)
    row["simulators"] = count_terms(text, SIMULATORS); row["unit_ops"] = count_terms(text, UNIT_OPS); row["cues"] = count_terms(text, CUES)
    row["chars_counted"] = len(text)
    return row


def run(seeds: list[str], out: str, max_urls: int = 60, robots: Robots | None = None, sleep=time.sleep, opener=None) -> list[dict]:
    robots = robots or Robots(); last: dict = {}; done = {}
    if os.path.exists(out):
        for l in open(out):
            r = json.loads(l); done[r["url"]] = r
    rows, dead_hosts = [], set()
    for url in seeds[:max_urls]:
        host = urllib.parse.urlsplit(url).netloc
        if url in done and done[url].get("status") != "error": continue                                # already indexed; a block is not retried (a person decides), only a transient error is
        if host in dead_hosts: rows.append({"url": url, "host": host, "status": "skipped-host-blocked", "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}); continue
        r = fetch_one(url, robots, opener, sleep, last); rows.append(r)
        if r.get("status") == "blocked": dead_hosts.add(host)                                         # stop on that host, never bypass
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "a") as f:
        for r in rows: f.write(json.dumps(r, sort_keys=True) + "\n")
    return rows


def main(argv):
    if not argv: print(__doc__); return 2
    out = "studies/sources/guides.jsonl"; mx = 60
    if "--out" in argv: out = argv[argv.index("--out") + 1]
    if "--max" in argv: mx = int(argv[argv.index("--max") + 1])
    seeds = [l.strip() for l in open(argv[0]) if l.strip() and not l.startswith("#")]
    for r in run(seeds, out, mx):
        sim = ",".join(f"{k}:{v}" for k, v in sorted((r.get("simulators") or {}).items(), key=lambda x: -x[1])[:3])
        print(f"{r['status']:20} {r['host'][:34]:34} {str(r.get('title') or '')[:52]:52} {sim}")
    return 0


if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
