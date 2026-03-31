import os
import json
import uuid
import math
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder, MultipartEncoderMonitor

class BunkrUploader:
    def __init__(self, token):
        self.token = token.strip().strip("'").strip('"') # Clean up any quotes
        self.headers = {
            "token": self.token,
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.upload_url = None
        self.max_file_size = 0
        self.chunk_size = 52428800  # 50MB

    def verify_and_setup(self):
        """Verifies token and finds the optimal upload node."""
        # 1. Verify token
        try:
            # Note: The original script used POST to verify tokens
            verify_resp = requests.post(
                "https://dash.bunkr.cr/api/tokens/verify",
                data={"token": self.token},
                headers={"User-Agent": self.headers["User-Agent"]}, # No token header for verify call itself usually
                timeout=15
            )
            verify_resp.raise_for_status()
            v_data = verify_resp.json()
            if not v_data.get("success"):
                raise Exception(f"Token invalid: {v_data.get('message', 'Unspecified error')}")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                raise Exception("Access Forbidden (403): Bunkr may be blocking your connection or the token is definitely wrong.")
            raise Exception(f"Failed to verify token: {e}")

        # 2. Get upload node
        try:
            node_resp = requests.get(
                "https://dash.bunkr.cr/api/node", headers=self.headers, timeout=15
            )
            node_resp.raise_for_status()
            node_data = node_resp.json()
            if not node_data.get("success"):
                raise Exception("API denied access to upload nodes.")
            
            self.upload_url = node_data.get("url")
            if not self.upload_url:
                raise Exception("No upload server URL returned.")
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 403:
                raise Exception("Access Forbidden (403): Could not retrieve upload node. Is your token valid?")
            raise Exception(f"Failed to get upload node: {e}")

        # 3. Get server limits
        try:
            check_resp = requests.get(
                "https://dash.bunkr.cr/api/check", headers=self.headers, timeout=15
            )
            if check_resp.status_code == 200:
                check_data = check_resp.json()
                raw_chunk = check_data.get("chunkSize", {}).get("default", str(self.chunk_size))
                raw_max = check_data.get("maxSize", "104857600")
                self.chunk_size = self._parse_size(raw_chunk)
                self.max_file_size = int(self._parse_size(raw_max) * 0.95)
        except:
            pass # Use defaults if limits check fails

    def _parse_size(self, size_str):
        if not isinstance(size_str, str): return int(size_str)
        s = size_str.upper().strip()
        if s.endswith("GB"): return int(float(s[:-2]) * 1024**3)
        if s.endswith("MB"): return int(float(s[:-2]) * 1024**2)
        if s.endswith("KB"): return int(float(s[:-2]) * 1024)
        if s.endswith("B"):  return int(float(s[:-1]))
        try: return int(float(s))
        except: return 0

    def get_album_files(self, album_id):
        all_files = []
        page = 0
        headers = self.headers.copy()
        if album_id: headers["Filters"] = f"albumid:{album_id}"

        while True:
            url = f"https://dash.bunkr.cr/api/uploads/{page}"
            try:
                resp = requests.get(url, headers=headers, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                
                # Bunkr API can return either a list directly or a dict with a 'files' key
                files = data.get("files", []) if isinstance(data, dict) else data
                
                if not files:
                    break
                    
                all_files.extend(files)
                
                # If we get fewer than the likely page size, we might be at the end.
                # But to be safe, we check if the next page returns anything.
                # Historically Bunkr uses 50, but let's just increment and check 'if not files'.
                if len(files) < 10: # Very likely the last page
                     break

                page += 1
                if page > 1000: # Safety break
                    break
            except Exception as e:
                # If we hit an error after some pages, return what we have
                if all_files:
                    break
                raise e
        return all_files

    def create_album(self, name, public=False):
        # Fetch albums to check if it exists
        resp = requests.get("https://dash.bunkr.cr/api/albums", headers=self.headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        albums = data.get("albums", []) if isinstance(data, dict) else data
        
        album_id = None
        for a in albums:
            if a.get("name", "").lower() == name.lower():
                album_id = a["id"]
                # If found and we want it public but it might not be, we'll hit update below
                break

        if not album_id:
            # Create new album
            payload = {"name": name}
            if public:
                payload["public"] = 1
                
            resp = requests.post("https://dash.bunkr.cr/api/albums", headers=self.headers, json=payload, timeout=15)
            resp.raise_for_status()
            res = resp.json()
            if not res.get("success"): raise Exception(f"Create album failed: {res}")
            album_id = res["id"]
        
        # Optionally update public status if it exists but might be private
        # Only do this if public is specifically requested
        if public:
            requests.post(f"https://dash.bunkr.cr/api/albums/{album_id}", headers=self.headers, json={"public": 1}, timeout=10)
            
        return album_id

    def upload_file(self, file_path, album_id=None, progress_callback=None):
        if not self.upload_url: self.verify_and_setup()
        size = os.path.getsize(file_path)
        name = os.path.basename(file_path)
        if size <= self.chunk_size:
            return self._upload_single(file_path, name, size, album_id, progress_callback)
        return self._upload_chunked(file_path, name, size, album_id, progress_callback)

    def _upload_single(self, path, name, size, album_id, cb):
        headers = self.headers.copy()
        if album_id: headers["albumid"] = str(album_id)
        with open(path, "rb") as f:
            m = MultipartEncoder(fields={"files[]": (name, f, "application/octet-stream")})
            mon = MultipartEncoderMonitor(m, lambda mon: cb(mon.bytes_read/mon.len) if cb else None)
            headers["Content-Type"] = mon.content_type
            resp = requests.post(self.upload_url, headers=headers, data=mon, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"): raise Exception(f"Upload failed: {data}")
            return data.get("files", [{}])[0].get("url")

    def _upload_chunked(self, path, name, total_size, album_id, cb):
        total_chunks = math.ceil(total_size / self.chunk_size)
        file_uuid = str(uuid.uuid4())
        with open(path, "rb") as f:
            for i in range(total_chunks):
                chunk = f.read(self.chunk_size)
                fields = {
                    "dzuuid": file_uuid, "dzchunkindex": str(i),
                    "dztotalfilesize": str(total_size), "dzchunksize": str(self.chunk_size),
                    "dztotalchunkcount": str(total_chunks), "dzchunkbyteoffset": str(i * self.chunk_size),
                    "files[]": (name, chunk, "application/octet-stream"),
                }
                m = MultipartEncoder(fields=fields)
                headers = self.headers.copy()
                headers["Content-Type"] = m.content_type
                requests.post(self.upload_url, headers=headers, data=m, timeout=120).raise_for_status()
                if cb: cb((i + 1) / total_chunks * 0.95)
        
        # Finish
        body = {"files": [{"uuid": file_uuid, "original": name, "type": "application/octet-stream", "albumid": int(album_id) if album_id else None}]}
        resp = requests.post(f"{self.upload_url}/finishchunks", headers=self.headers, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("success"): raise Exception(f"Finish failed: {data}")
        if cb: cb(1.0)
        return data.get("files", [{}])[0].get("url")
