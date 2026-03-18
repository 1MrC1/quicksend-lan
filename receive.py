#!/usr/bin/env python3
"""Threaded parallel-chunk file receive server."""
import http.server, socketserver, os, sys, threading, socket

SAVE_DIR = os.path.expanduser("~/Downloads/received")
CHUNK_DIR = os.path.join(SAVE_DIR, ".chunks")
LOCK = threading.Lock()
PROGRESS = {}

# Sender script served via GET /__send__
SENDER_SCRIPT = r'''#!/usr/bin/env python3
"""Parallel file sender. Usage: python3 send.py HOST:PORT file1 [file2 ...]"""
import http.client, sys, os, threading, time

THREADS = 8
BUF = 4 * 1024 * 1024  # 4MB

def upload_chunk(host, port, filepath, filename, idx, offset, size, total, progress):
    conn = http.client.HTTPConnection(host, port, timeout=600)
    conn.putrequest("PUT", f"/{filename}/chunk_{idx}")
    conn.putheader("Content-Length", str(size))
    conn.putheader("X-Total-Chunks", str(total))
    conn.endheaders()
    with open(filepath, "rb") as f:
        f.seek(offset)
        remaining = size
        while remaining > 0:
            data = f.read(min(BUF, remaining))
            if not data:
                break
            conn.send(data)
            remaining -= len(data)
            progress[idx] = size - remaining
    resp = conn.getresponse()
    resp.read()
    conn.close()

def send_file(host, port, filepath, threads=THREADS):
    filename = os.path.basename(filepath)
    filesize = os.path.getsize(filepath)
    chunk_size = (filesize + threads - 1) // threads
    n = sum(1 for i in range(threads) if i * chunk_size < filesize)
    print(f"\n{filename} ({filesize / (1024**3):.2f} GB) -> {n} streams")
    progress = {}
    workers = []
    for i in range(n):
        offset = i * chunk_size
        size = min(chunk_size, filesize - offset)
        progress[i] = 0
        t = threading.Thread(target=upload_chunk,
                             args=(host, port, filepath, filename, i, offset, size, n, progress))
        t.start()
        workers.append(t)
    start = time.time()
    while any(t.is_alive() for t in workers):
        sent = sum(progress.values())
        elapsed = time.time() - start
        speed = sent / elapsed if elapsed > 0 else 0
        pct = sent * 100 / filesize if filesize else 100
        print(f"\r  {sent/(1024**3):.2f}/{filesize/(1024**3):.2f} GB "
              f"({pct:.0f}%) {speed/(1024**2):.0f} MB/s", end="", flush=True)
        time.sleep(0.3)
    for t in workers:
        t.join()
    elapsed = time.time() - start
    speed = filesize / elapsed if elapsed > 0 else 0
    print(f"\r  {filesize/(1024**3):.2f}/{filesize/(1024**3):.2f} GB "
          f"(100%) {speed/(1024**2):.0f} MB/s avg     ")
    conn = http.client.HTTPConnection(host, port, timeout=600)
    conn.request("PUT", f"/{filename}/done",
                 headers={"X-Total-Chunks": str(n)})
    resp = conn.getresponse()
    resp.read()
    conn.close()
    print(f"  -> {filename} done")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python3 {sys.argv[0]} HOST:PORT file1 [file2 ...]")
        sys.exit(1)
    hp = sys.argv[1].split(":")
    host = hp[0]
    port = int(hp[1]) if len(hp) > 1 else 9000
    for fp in sys.argv[2:]:
        if os.path.isfile(fp):
            send_file(host, port, fp)
        else:
            print(f"Skipping {fp} (not a file)")
'''


class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path == "/__send__":
            data = SENDER_SCRIPT.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        parts = [p for p in self.path.strip("/").split("/") if p]

        if len(parts) == 2 and parts[1].startswith("chunk_"):
            self._recv_chunk(parts[0], parts[1])
        elif len(parts) == 2 and parts[1] == "done":
            self._reassemble(parts[0])
        elif len(parts) == 1:
            self._recv_single(parts[0])
        else:
            self.send_response(400)
            self.end_headers()

    def _recv_chunk(self, filename, chunk_name):
        chunk_dir = os.path.join(CHUNK_DIR, filename)
        os.makedirs(chunk_dir, exist_ok=True)
        length = int(self.headers.get("Content-Length", 0))
        chunk_path = os.path.join(chunk_dir, chunk_name)
        received = 0
        with open(chunk_path, "wb") as f:
            while received < length:
                data = self.rfile.read(min(4194304, length - received))
                if not data:
                    break
                f.write(data)
                received += len(data)
        with LOCK:
            p = PROGRESS.setdefault(filename, {"n": 0, "bytes": 0})
            p["n"] += 1
            p["bytes"] += received
            print(f"  {filename}: {chunk_name} received "
                  f"({received/(1024**2):.0f} MB) "
                  f"[{p['n']} chunks, {p['bytes']/(1024**3):.2f} GB]")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK\n")

    def _reassemble(self, filename):
        total = int(self.headers.get("X-Total-Chunks", 0))
        chunk_dir = os.path.join(CHUNK_DIR, filename)
        out_path = os.path.join(SAVE_DIR, filename)
        print(f"  Reassembling {filename} ({total} chunks)...")
        with open(out_path, "wb") as out:
            for i in range(total):
                cp = os.path.join(chunk_dir, f"chunk_{i}")
                with open(cp, "rb") as cf:
                    while True:
                        data = cf.read(4194304)
                        if not data:
                            break
                        out.write(data)
                os.remove(cp)
        try:
            os.rmdir(chunk_dir)
        except OSError:
            pass
        size = os.path.getsize(out_path)
        with LOCK:
            PROGRESS.pop(filename, None)
        print(f"  >> DONE: {filename} ({size/(1024**3):.2f} GB) -> {out_path}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"OK {size}\n".encode())

    def _recv_single(self, name):
        """Backwards-compat: single-stream upload."""
        length = int(self.headers.get("Content-Length", 0))
        path = os.path.join(SAVE_DIR, name)
        received = 0
        with open(path, "wb") as f:
            while received < length:
                data = self.rfile.read(min(4194304, length - received))
                if not data:
                    break
                f.write(data)
                received += len(data)
                print(f"\r  {name}: {received/(1024**3):.2f}/"
                      f"{length/(1024**3):.2f} GB "
                      f"({received*100//length}%)", end="", flush=True)
        print(f"\n  >> Saved {path} ({received} bytes)")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK\n")

    def log_message(self, *a):
        pass


class ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


if __name__ == "__main__":
    os.makedirs(SAVE_DIR, exist_ok=True)
    os.makedirs(CHUNK_DIR, exist_ok=True)
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    srv = ThreadedServer(("0.0.0.0", port), Handler)
    srv.socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4 * 1024 * 1024)
    print(f"Parallel receive server on :{port} -> {SAVE_DIR}/")
    print(f"Sender setup (run on other Mac):")
    print(f"  curl http://192.168.1.101:{port}/__send__ -o /tmp/send.py")
    print(f"  python3 /tmp/send.py 192.168.1.101:{port} file1 file2 ...")
    print()
    srv.serve_forever()
