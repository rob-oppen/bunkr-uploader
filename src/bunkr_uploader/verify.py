import os
import sys
import argparse
import json
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from .api import BunkrUploader

console = Console()

def load_log(p):
    if not os.path.exists(p): return []
    with open(p, encoding="utf-8") as f: return [l.strip() for l in f if l.strip()]

def save_log(p, es):
    with open(p, "w", encoding="utf-8") as f:
        for e in es: f.write(f"{e}\n")

def main(argv=None):
    if argv is None: argv = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("-t", "--token")
    parser.add_argument("-a", "--album", type=int)
    parser.add_argument("--requeue", action="store_true")
    args = parser.parse_args(argv)
    token = args.token or os.environ.get("BUNKR_TOKEN")
    if not (token and args.album): return console.print("[red]Token and Album ID required") or 1
    dir_p = os.path.abspath(args.file)
    log_p = os.path.join(dir_p, "uploaded_bunkr.log")
    uploader = BunkrUploader(token)
    uploader.verify_and_setup()
    
    remote_files = uploader.get_album_files(args.album)
    remote_names = {f.get("original") or f.get("name") for f in remote_files}
    remote_by_size = {}
    for f in remote_files:
        s = int(f.get("size") or 0)
        if s > 0:
            if s not in remote_by_size: remote_by_size[s] = []
            remote_by_size[s].append(f.get("original") or f.get("name"))

    logged = load_log(log_p)
    present = []
    missing = []

    for name in logged:
        # 1. Exact match
        if name in remote_names:
            present.append(name)
            continue
        
        # 2. Check local file size if it exists to match against remote
        full_p = os.path.join(dir_p, name)
        found_by_size = False
        if os.path.exists(full_p):
            sz = os.path.getsize(full_p)
            if sz > 1024 * 1024 and sz in remote_by_size:
                ext = os.path.splitext(name)[1].lower()
                for r_name in remote_by_size[sz]:
                     if r_name.lower().endswith(ext):
                         present.append(name)
                         found_by_size = True
                         break
        
        if not found_by_size:
            missing.append(name)

    summary = Table(box=box.ROUNDED)
    summary.add_column("Metric")
    summary.add_column("Count")
    summary.add_row("Logged", str(len(logged)))
    summary.add_row("Present", f"[green]{len(present)}")
    summary.add_row("Missing", f"[red]{len(missing)}")
    console.print(Panel(summary, title="Summary"))
    if args.requeue and missing:
        save_log(log_p, present)
        console.print("[green]Requeued missing files (updated log)")
    return 0

if __name__ == "__main__": sys.exit(main())
