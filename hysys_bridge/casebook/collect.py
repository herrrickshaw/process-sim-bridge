"""Polite collector for public university guides and exercises on process simulation (Aspen, HYSYS, DWSIM and others).
It builds an INDEX, not a copy: for each URL it records where the page is, what it is, which simulators and unit operations it mentions, and whether it carries
a licence hint. Page text is never stored (course notes are copyrighted by their authors); keyword counts are computed in memory and thrown away.

Rules it keeps (CLAUDE.md, "Source fetching"): one request per second per host at most (a longer robots.txt crawl-delay wins); robots.txt is checked before every
fetch, for this collector's own agent and for Claude-User, and a site that disallows either is skipped; only a missing robots.txt (404 or 410) means no rules,
any other failure to read it means skip; a captcha, robot check, WAF challenge or login wall ends
work on that host and is recorded, never bypassed; one page per seed URL (no link following); size capped. Seeds come from a file the operator controls.
Redirects are followed by hand, at most MAX_REDIRECTS, http and https only: every hop gets its own robots.txt check and per-host delay, a blocked host stays
closed, and a redirect to a different host must lead to a public address (checked by name lookup just before the request, so DNS rebinding is not covered).

    python3 -m hysys_bridge.casebook.collect studies/sources/seeds.txt [--out studies/sources/guides.jsonl] [--max 60]
"""
from __future__ import annotations
import datetime, hashlib, ipaddress, json, os, re, shutil, socket, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, urllib.robotparser
from html.parser import HTMLParser

AGENT = "process-sim-bridge-collector"
UA = f"{AGENT}/0.1 (index of public teaching material; honours robots.txt)"
ALSO_RESPECT = "Claude-User"                  # robots rules written for the assistant that runs this are honoured too
MAX_BYTES = 25 * 1024 * 1024
MIN_DELAY = 1.0
MAX_REDIRECTS = 5
REDIRECT_CODES = (301, 302, 303, 307, 308)
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


class _NoAutoRedirect(urllib.request.HTTPRedirectHandler):
    """A 3xx comes back as HTTPError, so each hop is checked before it is requested. The standard handler is replaced outright
    because it reads Location itself and raises on a malformed one."""
    def _leave_it(self, *args): return None
    http_error_301 = http_error_302 = http_error_303 = http_error_307 = http_error_308 = _leave_it


_open = urllib.request.build_opener(_NoAutoRedirect).open


def _is_http(url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    return p.scheme in ("http", "https") and bool(p.hostname)


def _is_public(host: str) -> bool:
    """True only if every address the name resolves to is a public one."""
    try: addresses = {info[4][0].split("%")[0] for info in socket.getaddrinfo(host, None)}
    except (OSError, UnicodeError): return False
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


def _next_hop(current: str, location: str | None, seed: str) -> tuple[str | None, str]:
    """(url to request next, "") or (None, why this redirect is not followed). The reason never repeats the target: it may carry tokens or credentials."""
    if not location: return None, "redirect without a Location"
    try:
        target = urllib.parse.urldefrag(urllib.parse.urljoin(current, location.strip()))[0]
        if not _is_http(target): return None, "redirect to something other than http or https"
        p = urllib.parse.urlsplit(target)
        if "@" in p.netloc: return None, "redirect carries credentials"
        if p.hostname != urllib.parse.urlsplit(seed).hostname and not _is_public(p.hostname):
            return None, "redirect to another host that is not at a public address"
    except ValueError: return None, "redirect target is not a valid URL"
    return target, ""


def _without_query(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, "", ""))


def _request(url: str, accept: str | None = None):
    safe = urllib.parse.quote(url, safe=":/?&=%#~+@,;[]")
    return urllib.request.Request(safe, headers={"User-Agent": UA, **({"Accept": accept} if accept else {})})


class Robots:
    """robots.txt per host, fetched once; allowed only if both the collector's agent and Claude-User may fetch the URL."""
    def __init__(self, fetch=None): self.cache: dict[str, urllib.robotparser.RobotFileParser | None] = {}; self.fetch = fetch or self._fetch
    @staticmethod
    def _fetch(url):
        seed = url
        for _ in range(MAX_REDIRECTS + 1):
            try:
                with _open(_request(url), timeout=20) as r: return r.status, r.read(512 * 1024).decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code not in REDIRECT_CODES: raise
                url, why = _next_hop(url, e.headers.get("Location"), seed)
                if why: raise ValueError(why)
        raise ValueError("robots.txt redirects too many times")
    def _parser(self, base):
        if base not in self.cache:
            rp = urllib.robotparser.RobotFileParser()
            try:
                st, body = self.fetch(base + "/robots.txt"); rp.parse(body.splitlines())
                if body.lstrip().startswith("<") and CHALLENGE.search(body[:6000]): rp = "a challenge or login page"
            except urllib.error.HTTPError as e: rp = None if e.code in (404, 410) else f"HTTP {e.code}"     # only a missing file means there are no rules
            except Exception: rp = "unreachable"
            self.cache[base] = rp
        return self.cache[base]
    def check(self, url: str) -> tuple[bool, str, float]:
        p = urllib.parse.urlsplit(url); base = f"{p.scheme}://{p.netloc}"; rp = self._parser(base)
        if rp is None: return True, "no robots.txt", 0.0
        if rp == "unreachable": return False, "robots.txt unreachable, not guessing", 0.0
        if isinstance(rp, str): return False, f"robots.txt answered {rp}, not guessing", 0.0
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


def fetch_one(url: str, robots: Robots, opener=None, sleep=time.sleep, last: dict | None = None, dead_hosts: set | None = None) -> dict:
    """One row for one URL. `last` maps host -> time of the previous request, for the per-host delay; `dead_hosts` are hosts that blocked earlier.
    A supplied `opener` must not follow redirects itself."""
    last = last if last is not None else {}
    row = {"url": url, "host": urllib.parse.urlsplit(url).netloc, "fetched_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
    if not _is_http(url): row["status"] = "error"; row["why"] = "only http and https are fetched"; return row
    current = url
    for hop in range(MAX_REDIRECTS + 1):
        host = urllib.parse.urlsplit(current).netloc
        if host in (dead_hosts or ()): row["status"] = "skipped-host-blocked"; row["why"] = f"redirect leads to {host}, which blocked earlier"; return row
        ok, why, delay = robots.check(current)
        row["robots"] = why if hop == 0 else f"after redirect to {host}: {why}"
        if not ok: row["status"] = "skipped-robots"; return row
        wait = max(MIN_DELAY, delay) - (time.monotonic() - last.get(host, -1e9))
        if wait > 0: sleep(wait)
        last[host] = time.monotonic()
        try:
            with (opener or _open)(_request(current, "text/html,application/pdf;q=0.9,*/*;q=0.1"), timeout=40) as r:
                row["http"] = r.status; row["final_url"] = r.geturl() if hop == 0 else _without_query(current)
                ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower(); row["content_type"] = ctype
                data = r.read(MAX_BYTES + 1)
            break
        except urllib.error.HTTPError as e:
            if e.code in REDIRECT_CODES:
                current, refused = _next_hop(current, e.headers.get("Location"), url)
                if refused: row["http"] = e.code; row["status"] = "skipped-redirect"; row["why"] = refused; return row
                continue
            row["http"] = e.code; row["status"] = "blocked" if e.code in (401, 403, 429, 503) else "error"; row["why"] = f"HTTP {e.code}"
            if row["status"] == "blocked": row["blocked_host"] = host
            return row
        except Exception as e:
            row["status"] = "error"; row["why"] = f"{type(e).__name__}"; return row
    else:
        row["status"] = "skipped-redirect"; row["why"] = "too many redirects"; return row
    if len(data) > MAX_BYTES: row["status"] = "too-large"; row["bytes"] = f">{MAX_BYTES}"; return row
    row["bytes"] = len(data); row["sha256"] = hashlib.sha256(data).hexdigest()[:16]
    if ctype == "application/pdf" or data[:5] == b"%PDF-":
        text, title, pages = _pdf_facts(data); html = ""; row.update({"kind": "pdf", "title": title or None, "pages": pages})
    else:
        html = data.decode("utf-8", "replace"); p = _Title(); p.feed(html); text = re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(script|style).*?</\1>", " ", html)); row.update({"kind": "html", "title": p.t or None})
        if CHALLENGE.search(html[:6000]) and len(text.strip()) < 2500: row["status"] = "blocked"; row["why"] = "challenge or login wall"; row["blocked_host"] = host; return row
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
        r = fetch_one(url, robots, opener, sleep, last, dead_hosts); rows.append(r)
        if r.get("status") == "blocked": dead_hosts.add(r.get("blocked_host", host))                  # stop on the host that blocked, never bypass
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
