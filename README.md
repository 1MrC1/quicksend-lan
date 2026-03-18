# quicksend

Fast LAN file transfer between two Macs (or any machines). Multithreaded parallel chunked uploads over HTTP — no dependencies, pure Python stdlib.

Built because AirDrop chokes on large files.

## Usage

### Receiver (destination machine)

```bash
python3 receive.py
```

Listens on port `9000` by default. Files are saved to `~/Downloads/received/`.

```bash
python3 receive.py 8080  # custom port
```

### Sender (source machine)

Grab the sender script directly from the receiver:

```bash
curl http://<RECEIVER_IP>:9000/__send__ -o /tmp/send.py
```

Send files:

```bash
python3 /tmp/send.py <RECEIVER_IP>:9000 file1.iso file2.dmg
```

Send everything in a directory:

```bash
python3 /tmp/send.py <RECEIVER_IP>:9000 /path/to/files/*
```

Or copy `send.py` manually and run it the same way.

### Simple single-file mode

For quick one-off transfers, `curl` works too (single stream):

```bash
curl -T myfile.bin http://<RECEIVER_IP>:9000/
```

## How it works

- **Sender** splits each file into 8 chunks and uploads them in parallel threads over HTTP PUT
- **Receiver** runs a threaded HTTP server, writes chunks to disk, reassembles when all chunks arrive
- 4MB I/O buffers on both ends
- No temp files on the sender — each thread `seek()`s directly into the source file
- Progress bar with transfer speed on the sender side
- Zero dependencies — Python 3.6+ stdlib only

## Requirements

- Python 3.6+
- Both machines on the same network

## License

MIT
