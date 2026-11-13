#!/usr/bin/env python3
"""
ACAPULCO cerebellum QC app. Standard library only, no installs needed.

  python3 qc_app.py --data /path/to/QC_app_data/HCPD --rater EMD

Opens the app in your browser. Ratings save automatically to
<data>/ratings/ratings_<rater>.csv (and a .json copy the app reloads from).
"""
import argparse, csv, glob, json, os, posixpath, sys, tempfile, threading, time, webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, unquote

HERE = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(HERE, "static")
LOCK = threading.Lock()


def atomic_write(path, text):
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp_")
    with os.fdopen(fd, "w", newline="") as f:
        f.write(text)
    os.replace(tmp, path)


class QCHandler(SimpleHTTPRequestHandler):
    data_dir = None
    rater = None
    index = None

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        if not os.path.isfile(path):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(os.path.getsize(path)))
        self.end_headers()
        with open(path, "rb") as f:
            self.wfile.write(f.read())

    def _safe(self, root, rel):
        rel = posixpath.normpath(unquote(rel)).lstrip("/")
        full = os.path.realpath(os.path.join(root, rel))
        return full if full.startswith(os.path.realpath(root) + os.sep) else None

    def _ratings_paths(self):
        d = os.path.join(self.data_dir, "ratings")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "ratings_%s.json" % self.rater), os.path.join(d, "ratings_%s.csv" % self.rater)

    def _load_ratings(self):
        jp, _ = self._ratings_paths()
        return json.load(open(jp)) if os.path.exists(jp) else {}

    def _load_others(self):
        """Ratings from every other rater's file in the ratings folder (read-only)."""
        d = os.path.join(self.data_dir, "ratings")
        out = {}
        for jp in glob.glob(os.path.join(d, "ratings_*.json")):
            rater = os.path.basename(jp)[len("ratings_"):-len(".json")]
            if rater == self.rater:
                continue
            try:
                out[rater] = json.load(open(jp))
            except Exception:
                pass
        return out

    def _save_ratings(self, ratings):
        jp, cp = self._ratings_paths()
        atomic_write(jp, json.dumps(ratings, indent=1))
        names = [l["name"] for l in self.index["labels"]]
        rows = [["subject", "rater", "timestamp", "overall", "n_under", "n_over"]
                + names + ["notes"]]
        for sub in sorted(ratings):
            r = ratings[sub]
            lob = r.get("lobules", {})
            rows.append([sub, self.rater, r.get("timestamp", ""), r.get("overall", ""),
                         sum(1 for v in lob.values() if v == "Under"),
                         sum(1 for v in lob.values() if v == "Over")]
                        + [lob.get(n, "") for n in names] + [r.get("notes", "")])
        import io
        buf = io.StringIO()
        csv.writer(buf).writerows(rows)
        atomic_write(cp, buf.getvalue())

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/favicon.ico":
            self.send_response(204); self.end_headers(); return
        if p in ("/", "/index.html"):
            return self._file(os.path.join(STATIC, "index.html"), "text/html; charset=utf-8")
        if p.startswith("/static/"):
            f = self._safe(STATIC, p[len("/static/"):])
            return self._file(f, "application/javascript") if f else self.send_error(404)
        if p.startswith("/data/"):
            f = self._safe(os.path.join(self.data_dir, "subjects"), p[len("/data/"):])
            return self._file(f, "application/octet-stream") if f else self.send_error(404)
        if p == "/api/index":
            return self._json(dict(self.index, rater=self.rater))
        if p == "/api/ratings":
            with LOCK:
                return self._json({"mine": self._load_ratings(), "others": self._load_others()})
        self.send_error(404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/ratings":
            return self.send_error(404)
        n = int(self.headers.get("Content-Length", 0))
        try:
            msg = json.loads(self.rfile.read(n))
            sub = msg["subject"]
            if sub not in {s["id"] for s in self.index["subjects"]}:
                raise ValueError("unknown subject")
        except Exception as e:
            return self._json({"error": str(e)}, 400)
        with LOCK:
            ratings = self._load_ratings()
            ratings[sub] = {
                "overall": msg.get("overall", ""),
                "lobules": {k: v for k, v in msg.get("lobules", {}).items() if v in ("OK", "Under", "Over")},
                "notes": msg.get("notes", ""),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save_ratings(ratings)
        self._json({"ok": True, "timestamp": ratings[sub]["timestamp"]})


def main():
    ap = argparse.ArgumentParser(description="ACAPULCO cerebellum QC app")
    ap.add_argument("--data", required=True, help="QC folder made by qc_prep.py")
    ap.add_argument("--rater", required=True, help="your initials; ratings are saved per rater")
    ap.add_argument("--subjects", default=None,
                    help="text file with one subject ID per line; the app shows only those subjects (your assigned batch)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    idx = os.path.join(a.data, "index.json")
    if not os.path.exists(idx):
        sys.exit("No index.json in %s. Run qc_prep.py first." % a.data)
    QCHandler.data_dir = os.path.abspath(a.data)
    QCHandler.rater = "".join(c for c in a.rater if c.isalnum() or c in "-_") or "rater"
    QCHandler.index = json.load(open(idx))
    if a.subjects:
        want = [l.strip() for l in open(a.subjects) if l.strip()]
        known = {s["id"] for s in QCHandler.index["subjects"]}
        missing = [w for w in want if w not in known]
        QCHandler.index["subjects"] = [s for s in QCHandler.index["subjects"] if s["id"] in set(want)]
        print("Batch %s: %d subjects" % (os.path.basename(a.subjects), len(QCHandler.index["subjects"])))
        if missing:
            print("WARNING: %d IDs in the batch file are not in this dataset (first few: %s)"
                  % (len(missing), ", ".join(missing[:5])))
        if not QCHandler.index["subjects"]:
            sys.exit("None of the IDs in %s match this dataset. Check the file and --data folder." % a.subjects)
    srv = HTTPServer(("127.0.0.1", a.port), QCHandler)
    url = "http://127.0.0.1:%d/" % a.port
    print("QC app running at %s  (Ctrl-C to stop)" % url)
    print("Ratings save to %s" % os.path.join(QCHandler.data_dir, "ratings"))
    if not a.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
