import os
import sys
import argparse
import signal
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from rich.console import Console, Group
from rich.live import Live
from rich.progress import Progress, BarColumn, TextColumn, TimeRemainingColumn, DownloadColumn, SpinnerColumn
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich import box

from .api import BunkrUploader

console = Console()

class BunkrTUI:
    def __init__(self, connections):
        self.lock = Lock()
        self.total_files = 0
        self.completed_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.current_connections = connections
        
        # Recent activity log (last 10 items)
        self.recent_activity = []
        
        # Progress bars
        self.overall_progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            TextColumn("({task.completed}/{task.total} files)")
        )
        self.overall_task = None
        
        self.active_progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold cyan]{task.description}"),
            BarColumn(),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TimeRemainingColumn(),
        )
        
    def add_activity(self, status, filename):
        with self.lock:
            timestamp = datetime.now().strftime("%H:%M:%S")
            if status == "success":
                icon = "[green]✓[/green]"
            elif status == "skipped":
                icon = "[blue]↗[/blue]"
            else:
                icon = "[red]✗[/red]"
            
            # Strip long names for the activity log
            display_name = (filename[:50] + '..') if len(filename) > 50 else filename
            self.recent_activity.append(f"{timestamp} {icon} {display_name}")
            if len(self.recent_activity) > 10:
                self.recent_activity.pop(0)

    def update_overall(self):
        with self.lock:
            if self.overall_task is not None:
                # Completed includes successful + failed
                # Total remains the original file count
                self.overall_progress.update(self.overall_task, completed=self.completed_count + self.failed_count + self.skipped_count)

    def make_layout(self) -> Layout:
        with self.lock:
            layout = Layout()
            
            # Summary Panel
            summary_table = Table(box=None, expand=True)
            summary_table.add_column("Stat", style="dim")
            summary_table.add_column("Value", justify="right")
            summary_table.add_row("Parallel Slots", f"[bold]{self.current_connections}[/bold]")
            summary_table.add_row("Success", f"[green]{self.completed_count}[/green]")
            summary_table.add_row("Skipped (Existing)", f"[blue]{self.skipped_count}[/blue]")
            summary_table.add_row("Failed", f"[red]{self.failed_count}[/red]")
            summary_table.add_row("Total in Directory", str(self.total_files))

            # Recent Activity Table
            activity_table = Table(box=None, expand=True, show_header=False)
            activity_table.add_column("Log")
            for log in reversed(self.recent_activity):
                activity_table.add_row(log)

            top_panel = Panel(
                Group(
                    self.overall_progress,
                    summary_table
                ),
                title="[bold cyan]Bunkr Uploader Overview[/bold cyan]",
                border_style="cyan",
                box=box.ROUNDED
            )
            
            activity_panel = Panel(
                activity_table,
                title="[bold yellow]Recent Activity[/bold yellow]",
                border_style="yellow",
                box=box.ROUNDED,
                height=14
            )
            
            transfer_panel = Panel(
                self.active_progress,
                title="[bold blue]Active Transfers[/bold blue]",
                border_style="blue",
                box=box.ROUNDED,
                expand=True
            )

            # Build grid
            layout.split(
                Layout(top_panel, size=9), # Slightly bigger for skipped stat
                Layout(name="lower")
            )
            layout["lower"].split_row(
                Layout(transfer_panel, ratio=2),
                Layout(activity_panel, ratio=1)
            )
            
            return layout

def upload_worker(uploader, file_path, album_id, log_path, log_lock, tui):
    filename = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    
    # Add to active progress
    # Shorten filename in progress bar to prevent wrapping / overlap
    display_name = (filename[:35] + "..") if len(filename) > 37 else filename
    task_id = tui.active_progress.add_task(display_name, total=file_size)
    
    def on_progress(fraction):
        tui.active_progress.update(task_id, completed=int(fraction * file_size))

    try:
        uploader.upload_file(file_path, album_id=album_id, progress_callback=on_progress)
        
        # Mark as done in log
        with log_lock:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"{filename}\n")
        
        with tui.lock:
            tui.completed_count += 1
        tui.add_activity("success", filename)
        return True
    except Exception as e:
        with tui.lock:
            tui.failed_count += 1
        # Extract meaningful error
        err_str = str(e)
        if "403" in err_str: err_str = "Forbidden (403)"
        elif "Connection" in err_str: err_str = "Network Error"
        tui.add_activity("failed", f"{filename} ({err_str[:20]})")
        return False
    finally:
        tui.active_progress.remove_task(task_id)
        tui.update_overall()

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]
        
    parser = argparse.ArgumentParser(description="Bunkr Uploader with Advanced TUI")
    parser.add_argument("file", help="File or directory to upload")
    parser.add_argument("-t", "--token", help="API token")
    parser.add_argument("-f", "--folder", help="Target folder name")
    parser.add_argument("-a", "--album", type=int, help="Existing album ID")
    parser.add_argument("-c", "--connections", type=int, default=5, help="Parallel uploads")
    parser.add_argument("--public", action="store_true", help="Make album public")
    
    args = parser.parse_args(argv)
    
    token = args.token or os.environ.get("BUNKR_TOKEN")
    if not token:
        console.print("[red]Error:[/red] API token not found.")
        return 1

    target_path = os.path.abspath(args.file)
    if not os.path.exists(target_path):
        console.print(f"[red]Error:[/red] Path does not exist: {target_path}")
        return 1

    if os.path.isfile(target_path):
        files = [target_path]
        directory = os.path.dirname(target_path)
    else:
        directory = target_path
        files = [os.path.join(directory, f) for f in os.listdir(directory) if os.path.isfile(os.path.join(directory, f))]

    log_path = os.path.join(directory, "uploaded_bunkr.log")
    
    # Init Uploader
    uploader = BunkrUploader(token)
    try:
        uploader.verify_and_setup()
    except Exception as e:
        console.print(f"[red]API Error:[/red] {e}")
        return 1

    # Album Logic
    album_id = args.album
    if not album_id:
        folder_name = args.folder or os.path.basename(directory)
        album_id = uploader.create_album(folder_name, public=args.public)
    elif args.public:
        # If ID provided but --public also set, ensure it's public
        uploader.create_album(os.path.basename(directory), public=True)

    # Sync Phase
    reconciled = set()
    with console.status(f"[bold green]Syncing with Bunkr Album {album_id}...") as status:
        try:
            remote_files = uploader.get_album_files(album_id)
            
            # Map of remote files by their original filename and size
            remote_names = set()
            remote_by_size = {} # size -> list of original names
            
            for rf in remote_files:
                orig = rf.get("original") or rf.get("name")
                size = int(rf.get("size") or 0)
                if orig:
                    remote_names.add(orig)
                if size > 0:
                    if size not in remote_by_size: remote_by_size[size] = []
                    remote_by_size[size].append(orig)

            current_log = set()
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8") as f:
                    current_log = set(l.strip() for l in f if l.strip())
            
            # Match local files against remote ones
            for f_p in files:
                basename = os.path.basename(f_p)
                size = os.path.getsize(f_p)
                
                # 1. Exact name match
                if basename in remote_names:
                    reconciled.add(basename)
                    continue
                
                # 2. Log match (as fallback if remote sync is flaky)
                if basename in current_log:
                    # Double check size if possible or just trust log
                    reconciled.add(basename)
                    continue

                # 3. Size match (Experimental: if size is large and unique in album)
                # This helps with Mojibake (emojis mangled by API)
                if size > 1024 * 1024 and size in remote_by_size:
                    # If multiple files have the same size, we check if any of them
                    # share the same extension.
                    matching_remote_names = remote_by_size[size]
                    ext = os.path.splitext(basename)[1].lower()
                    for r_name in matching_remote_names:
                        if r_name.lower().endswith(ext):
                            reconciled.add(basename)
                            break
            
            # Re-write log to match our findings
            with open(log_path, "w", encoding="utf-8") as f:
                for n in sorted(reconciled): f.write(f"{n}\n")
        except Exception as e:
            console.print(f"[yellow]Sync warning:[/yellow] {e}. Falling back to clean log.")
            if os.path.exists(log_path):
                 with open(log_path, "r", encoding="utf-8") as f:
                    reconciled = set(l.strip() for l in f if l.strip())

    to_push = [f for f in files if os.path.basename(f) not in reconciled]
    skipped_count = len(files) - len(to_push)

    if not to_push:
        console.print(f"[bold green]✓ All {len(files)} files are already in album {album_id}. Nothing to do.[/bold green]")
        return 0

    # TUI Setup
    tui = BunkrTUI(args.connections)
    tui.total_files = len(files)
    tui.skipped_count = skipped_count
    tui.overall_task = tui.overall_progress.add_task("Queue Processing", total=tui.total_files)
    
    # Pre-populate activity with skipped count
    if skipped_count > 0:
        tui.add_activity("skipped", f"{skipped_count} files already exist")
    
    tui.update_overall()
    log_lock = Lock()
    
    try:
        with Live(tui.make_layout(), console=console, refresh_per_second=4, screen=True) as live:
            with ThreadPoolExecutor(max_workers=args.connections) as executor:
                futures = {executor.submit(upload_worker, uploader, f_p, album_id, log_path, log_lock, tui): f_p for f_p in to_push}
                
                try:
                    for _ in as_completed(futures):
                        live.update(tui.make_layout())
                except KeyboardInterrupt:
                    live.stop()
                    console.print("\n[yellow]Stopping uploads... cleaning up.[/yellow]")
                    executor.shutdown(wait=False, cancel_futures=True)
                    return 0
    except KeyboardInterrupt:
        pass

    console.print(f"\n[bold green]Batch upload finished! {tui.completed_count} uploaded, {tui.skipped_count} skipped.[/bold green]")
    return 0

if __name__ == "__main__":
    sys.exit(main())
