from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import uuid


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8765"))
DOWNLOAD_DIR = os.path.join(os.path.dirname(__file__), "downloads")

os.makedirs(DOWNLOAD_DIR, exist_ok=True)


class DownloadHandler(BaseHTTPRequestHandler):

    def _send_json(self, status_code, data):
        body = json.dumps(data).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()

        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Health check
        if parsed.path in ("/", "/health"):
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "InstaSave Downloader",
                },
            )
            return

        # Serve downloaded file
        if parsed.path.startswith("/file/"):
            self._serve_file(parsed.path)
            return

        self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/download":
            self._send_json(404, {"error": "Not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))

            raw_body = self.rfile.read(content_length)

            body = json.loads(raw_body.decode("utf-8"))

            url = str(body.get("url", "")).strip()

            if not url:
                self._send_json(
                    400,
                    {"error": "Instagram URL is required."},
                )
                return

            if not self._is_instagram_url(url):
                self._send_json(
                    400,
                    {
                        "error": (
                            "Only Instagram post and Reel URLs are supported."
                        )
                    },
                )
                return

            print()
            print(f"[+] Download requested:")
            print(url)

            file_path = self._download(url)

            if not file_path or not os.path.exists(file_path):
                self._send_json(
                    500,
                    {
                        "error": (
                            "yt-dlp did not produce a downloadable file."
                        )
                    },
                )
                return

            file_name = os.path.basename(file_path)

            print(f"[+] Download complete: {file_name}")

            self._send_json(
                200,
                {
                    "status": "success",
                    "fileName": file_name,
                    "downloadUrl": (
                        "/file/" + urllib.parse.quote(file_name)
                    ),
                },
            )

        except json.JSONDecodeError:
            self._send_json(
                400,
                {"error": "Invalid JSON request."},
            )

        except subprocess.TimeoutExpired:
            self._send_json(
                500,
                {"error": "Download timed out."},
            )

        except Exception as e:
            print(f"[!] Error: {e}")

            self._send_json(
                500,
                {
                    "error": "Download failed. Check the server console."
                },
            )

    def _serve_file(self, request_path):
        encoded_name = request_path[len("/file/"):]
        file_name = urllib.parse.unquote(encoded_name)

        # Prevent directory traversal.
        safe_name = os.path.basename(file_name)

        if safe_name != file_name:
            self._send_json(400, {"error": "Invalid file name."})
            return

        file_path = os.path.join(DOWNLOAD_DIR, safe_name)

        if not os.path.isfile(file_path):
            self._send_json(404, {"error": "File not found."})
            return

        extension = os.path.splitext(file_path)[1].lower()

        content_types = {
            ".mp4": "video/mp4",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
        }

        content_type = content_types.get(
            extension,
            "application/octet-stream",
        )

        file_size = os.path.getsize(file_path)

        print(f"[+] Sending file: {safe_name}")
        print(f"[+] Size: {file_size} bytes")

        try:
            with open(file_path, "rb") as file:
                self.send_response(200)

                self.send_header(
                    "Content-Type",
                    content_type,
                )

                self.send_header(
                    "Content-Length",
                    str(file_size),
                )

                self.send_header(
                    "Content-Disposition",
                    f'attachment; filename="{safe_name}"',
                )

                self.end_headers()

                while True:
                    chunk = file.read(1024 * 1024)

                    if not chunk:
                        break

                    self.wfile.write(chunk)

        except (BrokenPipeError, ConnectionResetError):
            print("[!] Client disconnected while receiving file.")

    def _download(self, url):
        job_id = uuid.uuid4().hex

        temp_dir = tempfile.mkdtemp(
            prefix=f"instasave_{job_id}_"
        )

        output_template = os.path.join(
            temp_dir,
            "media.%(ext)s",
        )

        try:
            command = [
                "yt-dlp",
                "--no-playlist",
                "-f",
                "bv*+ba/b",
                "--merge-output-format",
                "mp4",
                "-o",
                output_template,
                url,
            ]

            print("[+] Running yt-dlp...")

            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=180,
            )

            if result.stdout:
                print(result.stdout)

            if result.returncode != 0:
                if result.stderr:
                    print(result.stderr)

                raise RuntimeError("yt-dlp failed.")

            files = []

            for name in os.listdir(temp_dir):
                full_path = os.path.join(
                    temp_dir,
                    name,
                )

                if os.path.isfile(full_path):
                    files.append(full_path)

            if not files:
                raise RuntimeError(
                    "No downloaded file was found."
                )

            source_file = max(
                files,
                key=os.path.getsize,
            )

            extension = os.path.splitext(
                source_file
            )[1].lower()

            if extension not in {
                ".mp4",
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
            }:
                extension = ".mp4"

            final_name = (
                f"instasave_{job_id}{extension}"
            )

            final_path = os.path.join(
                DOWNLOAD_DIR,
                final_name,
            )

            shutil.move(
                source_file,
                final_path,
            )

            return final_path

        finally:
            shutil.rmtree(
                temp_dir,
                ignore_errors=True,
            )

    @staticmethod
    def _is_instagram_url(url):
        try:
            parsed = urllib.parse.urlparse(url)

            if parsed.scheme.lower() != "https":
                return False

            host = parsed.netloc.lower().split(":")[0]

            if host not in {
                "instagram.com",
                "www.instagram.com",
            }:
                return False

            path = parsed.path.rstrip("/").lower()

            return (
                path.startswith("/reel/")
                or path.startswith("/p/")
            )

        except Exception:
            return False


class InstaSaveServer(ThreadingHTTPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    server = InstaSaveServer(
        (HOST, PORT),
        DownloadHandler,
    )

    print()
    print("=" * 50)
    print("InstaSave Downloader Server")
    print("=" * 50)
    print(f"Server: http://localhost:{PORT}")
    print(f"Health: http://localhost:{PORT}/health")
    print("Press Ctrl+C to stop.")
    print("=" * 50)
    print()

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nStopping server...")

    finally:
        server.server_close()