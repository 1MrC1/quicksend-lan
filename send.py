#!/usr/bin/env python3
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
