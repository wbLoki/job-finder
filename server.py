"""Job Finder: a local web app that searches Welcome to the Jungle and Working Nomads.

Run:  python server.py        then open http://localhost:8765
"""
import json
import os
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import seen
from sources import workingnomads, wttj

PORT = int(os.environ.get("PORT", 8765))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
SOURCES = {"wttj": wttj, "wn": workingnomads}
pool = ThreadPoolExecutor(max_workers=4)


def parse(qs):
    one = lambda k, d="": (qs.get(k) or [d])[0].strip()
    many = lambda k: [v for x in qs.get(k, []) for v in x.split(",") if v]
    num = lambda k: float(one(k)) if one(k) else None
    return {
        "q": one("q"),
        "title_only": one("title_only", "1") == "1",
        "sources": many("sources") or list(SOURCES),
        "country": one("country").upper(),
        "city": one("city"),
        "category": one("category"),
        "language": one("language"),
        # "@country" means: follow the country picked for WTTJ, using its English name.
        "wn_location": one("country_name") if one("wn_location", "@country") == "@country" else one("wn_location"),
        "wn_category": one("wn_category"),
        "include_worldwide": one("include_worldwide", "1") == "1",
        "contracts": many("contracts"),
        "remote": many("remote"),
        "max_exp": num("max_exp"),
        "include_unspecified_exp": one("include_unspecified_exp", "1") == "1",
        "posted_days": num("posted_days"),
        "sort": one("sort", "newest"),
        "only_new": one("only_new", "0") == "1",
        "page": int(one("page", "0") or 0),
    }


SEEN_DELAY = 3  # seconds a search must stay on screen before it moves the "newest seen" mark
_pending = {}
_pending_lock = threading.Lock()


def _record_newest_later(name, ts):
    """Record ts unless another search replaces this one within SEEN_DELAY (e.g. while typing)."""
    timer = threading.Timer(SEEN_DELAY, lambda: seen.record(name, ts))
    timer.daemon = True
    with _pending_lock:
        old = _pending.get(name)
        if old:
            old.cancel()
        _pending[name] = timer
    timer.start()


def search_source(name, p):
    mod = SOURCES[name]
    mark = seen.baseline(name)
    if p["only_new"] and mark:
        p = {**p, "after_ts": mark}
    page = mod.search(p, p["page"])
    seen.annotate(name, page["hits"])
    if p["page"] == 0:
        page["new"] = page["total"] if not mark or p.get("after_ts") else mod.count_newer(p, mark)
        _record_newest_later(name, mod.newest(p))
    return page


def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        traceback.print_exc()
        return {"error": f"{type(e).__name__}: {e}"}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=STATIC, **kw)

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            sys.stderr.write("%s\n" % (fmt % args))

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path == "/api/meta":
            seen.start_visit()  # opening the page starts a visit: freeze what counts as seen
            futs = {k: pool.submit(safe, m.meta) for k, m in SOURCES.items()}
            return self.send_json({k: f.result() for k, f in futs.items()})
        if url.path == "/api/cities":
            return self.send_json(safe(wttj.cities, (qs.get("country") or [""])[0].upper()))
        if url.path == "/api/search":
            p = parse(qs)
            futs = {k: pool.submit(safe, search_source, k, p) for k in p["sources"] if k in SOURCES}
            return self.send_json({k: f.result() for k, f in futs.items()})
        return super().do_GET()

    def do_POST(self):
        if urllib.parse.urlparse(self.path).path == "/api/seen/clear":
            seen.clear()
            return self.send_json({"ok": True})
        self.send_error(404)


if __name__ == "__main__":
    threading.Thread(target=lambda: safe(workingnomads.jobs), daemon=True).start()  # warm the cache
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Job Finder running at {url}  (Ctrl+C to stop)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
