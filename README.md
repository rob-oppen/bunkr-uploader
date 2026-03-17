# Bunkr Uploader Tool

A robust multi-threaded Python tool for uploading files to Bunkr.cr with automatic album synchronization and batch processing.

## Features

- **Multi-threaded Uploads**: Uses a thread pool to upload multiple files concurrently.
- **Auto-Synchronization**: Checks the remote Bunkr album state before starting and updates the local log.
  - Adds files already on Bunkr to the local log to skip duplicates.
  - Clears missing files from the local log to trigger re-uploads.
- **Chunked Uploading**: Automatically handles large files by splitting them into chunks.
- **Real-time TUI**: Beautiful terminal interface using `rich` showing progress bars for each thread.
- **Verification Tool**: Includes a separate script to verify the integrity of your uploads.

## Setup

1. Clone this repository.
2. Install the package locally:
   ```bash
   python -m pip install bunkr_uploader
   ```
   This will install all dependencies and register the `bunkr_uploader` command.

3. (Optional) Set your API token as an environment variable:
   ```bash
   $env:BUNKR_TOKEN="your_token_here"  # PowerShell
   set BUNKR_TOKEN=your_token_here      # CMD
   ```

---

## 🚀 Usage (Terminal / PowerShell / CMD)

You can run these commands from any directory if your Python `Scripts` folder is in your PATH.

### Example commands
```bash
# Standard command
bunkr_uploader C:\path\to\your\folder -t TOKEN -a ALBUM_ID

# Alternative if PATH isn't set
python -m bunkr_uploader C:\path\to\your\folder -t TOKEN -a ALBUM_ID
```

---

## Options & Flags

### `bunkr_uploader`
```text
usage: bunkr_uploader [-h] [-t TOKEN] [-f FOLDER] [-a ALBUM] [-c CONNECTIONS] [-r RETRIES] [--no-save] file

positional arguments:
  file                  File or directory to look for files in to upload

options:
  -h, --help            show this help message and exit
  -t, --token TOKEN     API token for your account
  -f, --folder FOLDER   Folder name on Bunkr (overrides local dir name)
  -a, --album ALBUM     Existing Album ID to upload to (Optional)
  -c, --connections CONNECTIONS
                        Max parallel uploads (Default: 5)
  --no-save             Don't save uploaded file names to a log file
```

### Synchronization Logic
The tool automatically synchronizes with the Bunkr album before every upload:
1. It fetches the list of files already in the remote album.
2. It updates your local `.log` file so you don't waste time on duplicates.
3. If a file is in your local log but "vanished" from Bunkr, it clears the log entry to trigger an automatic re-upload.
