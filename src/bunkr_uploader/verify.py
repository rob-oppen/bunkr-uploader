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
    remote = {f.get("original") or f.get("name") for f in uploader.get_album_files(args.album)}
    logged = load_log(log_p)
    missing = [f for f in logged if f not in remote]
    present = [f for f in logged if f in remote]
    summary = Table(box=box.ROUNDED)
    summary.add_row("Logged", str(len(logged)))
    summary.add_row("Present", f"[green]{len(present)}")
    summary.add_row("Missing", f"[red]{len(missing)}")
    console.print(Panel(summary, title="Summary"))
    if args.requeue and missing:
        save_log(log_p, present)
        console.print("[green]Requeued missing files")
    return 0

if __name__ == "__main__": sys.exit(main())
