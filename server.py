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
        self.send_header(
            "Content-Type",
            "application/json; charset=utf-8",
        )
        self.send_header(
            "Content-Length",
            str(len(body)),
        )
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        # Temporary metadata diagnostic endpoint.
        if parsed.path == "/metadata":
            query = urllib.parse.parse_qs(parsed.query)
            url = query.get("url", [""])[0].strip()

            if not url:
                self._send_json(
                    400,
                    {"error": "Instagram URL is required."},
                )
                return

            if not self._is_instagram_url(url):
                self._send_json(
                    400,
                    {"error": "Invalid Instagram URL."},
                )
                return

            try:
                self._debug_metadata(url)

                self._send_json(
                    200,
                    {
                        "status": (
                            "Metadata check completed. "
                            "See server logs."
                        )
                    },
                )

            except subprocess.TimeoutExpired:
                self._send_json(
                    500,
                    {"error": "Metadata check timed out."},
                )

            except Exception as e:
                print(f"[!] Metadata check error: {e}")

                self._send_json(
                    500,
                    {"error": "Metadata check failed."},
                )

            return

        # Temporary format diagnostic endpoint.
        if parsed.path == "/formats":
            query = urllib.parse.parse_qs(parsed.query)
            url = query.get("url", [""])[0].strip()

            if not url:
                self._send_json(
                    400,
                    {"error": "Instagram URL is required."},
                )
                return

            if not self._is_instagram_url(url):
                self._send_json(
                    400,
                    {"error": "Invalid Instagram URL."},
                )
                return

            try:
                self._debug_formats(url)

                self._send_json(
                    200,
                    {
                        "status": (
                            "Format check completed. "
                            "See server logs."
                        )
                    },
                )

            except subprocess.TimeoutExpired:
                self._send_json(
                    500,
                    {"error": "Format check timed out."},
                )

            except Exception as e:
                print(f"[!] Format check error: {e}")

                self._send_json(
                    500,
                    {"error": "Format check failed."},
                )

            return

        # Health check.
        if parsed.path in ("/", "/health"):
            self._send_json(
                200,
                {
                    "status": "ok",
                    "service": "InstaSave Downloader",
                },
            )
            return

        # Serve downloaded file.
        if parsed.path.startswith("/file/"):
            self._serve_file(parsed.path)
            return

        self._send_json(
            404,
            {"error": "Not found"},
        )

    def _debug_metadata(self, url):
        print()
        print("[+] Checking Instagram raw metadata...")
        print(url)

        command = [
            "yt-dlp",
            "--verbose",
            "--no-playlist",
            "--impersonate",
            "Chrome-150",
            "-J",
            url,
        ]

        print("[+] Running metadata check...")
        print("[+] Impersonation: Chrome-150")

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )

        print()
        print("=== RAW METADATA CHECK OUTPUT ===")

        if result.stdout:
            try:
                data = json.loads(result.stdout)

                formats = data.get("formats", [])

                print(
                    f"[+] Number of formats: {len(formats)}"
                )

                for media in formats:
                    print(
                        json.dumps(
                            {
                                "format_id": media.get("format_id"),
                                "ext": media.get("ext"),
                                "width": media.get("width"),
                                "height": media.get("height"),
                                "vcodec": media.get("vcodec"),
                                "acodec": media.get("acodec"),
                                "abr": media.get("abr"),
                                "url_present": bool(
                                    media.get("url")
                                ),
                            },
                            ensure_ascii=False,
                        )
                    )

            except json.JSONDecodeError:
                print(result.stdout)

        if result.stderr:
            print(result.stderr)

        print("=== END RAW METADATA CHECK OUTPUT ===")
        print()

        if result.returncode != 0:
            raise RuntimeError(
                "yt-dlp metadata check failed."
            )

    def _debug_formats(self, url):
        print()
        print("[+] Checking Instagram formats...")
        print(url)

        command = [
            "yt-dlp",
            "--verbose",
            "--no-playlist",
            "--impersonate",
            "Chrome-150",
            "-F",
            url,
        ]

        print("[+] Running format check...")
        print("[+] Impersonation: Chrome-150")

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=120,
        )

        print()
        print("=== FORMAT CHECK OUTPUT ===")

        if result.stdout:
            print(result.stdout)

        if result.stderr:
            print(result.stderr)

        print("=== END FORMAT CHECK OUTPUT ===")
        print()

        if result.returncode != 0:
            raise RuntimeError(
                "yt-dlp format check failed."
            )

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path != "/download":
            self._send_json(
                404,
                {"error": "Not found"},
            )
            return

        try:
            content_length = int(
                self.headers.get("Content-Length", "0")
            )

            raw_body = self.rfile.read(content_length)

            body = json.loads(
                raw_body.decode("utf-8")
            )

            url = str(
                body.get("url", "")
            ).strip()

            if not url:
                self._send_json(
                    400,
                    {
                        "error": "Instagram URL is required.",
                    },
                )
                return

            if not self._is_instagram_url(url):
                self._send_json(
                    400,
                    {
                        "error": (
                            "Only Instagram post and "
                            "Reel URLs are supported."
                        )
                    },
                )
                return

            print()
            print("[+] Download requested:")
            print(url)

            file_path = self._download(url)

            if not file_path or not os.path.exists(file_path):
                self._send_json(
                    500,
                    {
                        "error": (
                            "yt-dlp did not produce "
                            "a downloadable file."
                        )
                    },
                )
                return

            file_name = os.path.basename(file_path)

            print(
                f"[+] Download complete: {file_name}"
            )

            self._check_audio_stream(file_path)

            self._send_json(
                200,
                {
                    "status": "success",
                    "fileName": file_name,
                    "downloadUrl": (
                        "/file/"
                        + urllib.parse.quote(file_name)
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
                    "error": (
                        "Download failed. "
                        "Check the server console."
                    )
                },
            )

    def _serve_file(self, request_path):
        encoded_name = request_path[len("/file/"):]

        file_name = urllib.parse.unquote(
            encoded_name
        )

        # Prevent directory traversal.
        safe_name = os.path.basename(file_name)

        if safe_name != file_name:
            self._send_json(
                400,
                {"error": "Invalid file name."},
            )
            return

        file_path = os.path.join(
            DOWNLOAD_DIR,
            safe_name,
        )

        if not os.path.isfile(file_path):
            self._send_json(
                404,
                {"error": "File not found."},
            )
            return

        extension = os.path.splitext(
            file_path
        )[1].lower()

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

        file_size = os.path.getsize(
            file_path
        )

        print(
            f"[+] Sending file: {safe_name}"
        )
        print(
            f"[+] Size: {file_size} bytes"
        )

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
                    chunk = file.read(
                        1024 * 1024
                    )

                    if not chunk:
                        break

                    self.wfile.write(chunk)

        except (
            BrokenPipeError,
            ConnectionResetError,
        ):
            print(
                "[!] Client disconnected "
                "while receiving file."
            )

    def _download(self, url):
        job_id = uuid.uuid4().hex
        temp_dir = tempfile.mkdtemp(prefix=f"instasave_{job_id}_")
        
        try:
            # Step 1: Download the file using yt-dlp
            # We use a simpler format selector to get the most reliable file first
            input_template = os.path.join(temp_dir, "input.%(ext)s")
            command = [
                "yt-dlp",
                "--no-playlist",
                "--user-agent", "Mozilla/5.0 (Linux; Android 13; SM-S901B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Mobile Safari/537.36",
                "-f", "bestvideo+bestaudio/best",
                "--merge-output-format", "mp4",
                "-o", input_template,
                url,
            ]
            
            print(f"[+] Downloading raw media for: {url}")
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            if result.returncode != 0:
                raise RuntimeError("yt-dlp failed to download media.")

            # Find the downloaded file
            files = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir)]
            if not files:
                raise RuntimeError("No file was downloaded.")
            input_file = max(files, key=os.path.getsize)
            
            # Step 2: MANUALLY FORCE CONVERSION using FFmpeg
            # This is the critical part. We bypass yt-dlp's internal logic
            # and force a full rewrite of the audio and video streams.
            final_name = f"instasave_{job_id}.mp4"
            final_path = os.path.join(DOWNLOAD_DIR, final_name)
            
            print(f"[+] Forcing universal compatibility conversion...")
            convert_command = [
                "ffmpeg",
                "-i", input_file,
                "-c:v", "copy",      # Copy video as-is (FAST, no CPU usage)
                "-c:a", "aac",       # Force Standard AAC (Universal Audio)
                "-b:a", "128k",      # Standard bitrate
                "-ac", "2",          # Force stereo
                "-movflags", "+faststart", # Optimization for mobile playback
                "-y",
                final_path,
            ]
            
            conv_result = subprocess.run(convert_command, capture_output=True, text=True, timeout=120)
            if conv_result.returncode != 0:
                print(f"[!] FFmpeg conversion failed: {conv_result.stderr}")
                # Fallback: if conversion fails, try to just move the original
                shutil.move(input_file, final_path)
            
            return final_path

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _check_audio_stream(file_path):
        """
        Check whether the final downloaded MP4
        actually contains an audio stream.
        """

        print("[+] Checking final MP4 audio stream...")

        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=codec_name",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    file_path,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            codec = result.stdout.strip()

            if codec:
                print(
                    f"[+] Audio stream detected: {codec}"
                )
            else:
                print(
                    "[!] NO AUDIO STREAM detected "
                    "in final MP4."
                )

        except FileNotFoundError:
            print(
                "[!] ffprobe is not available. "
                "Could not check audio stream."
            )

        except Exception as e:
            print(
                f"[!] Audio check failed: {e}"
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
    print(
        f"Server: http://localhost:{PORT}"
    )
    print(
        f"Health: http://localhost:{PORT}/health"
    )
    print("Press Ctrl+C to stop.")
    print("=" * 50)
    print()

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        print("\nStopping server...")

    finally:
        server.server_close()
