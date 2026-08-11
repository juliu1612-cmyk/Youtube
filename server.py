#!/usr/bin/env python3
"""
YouTube Downloader - Desktop Tool (macOS + Windows)
Python backend server using built-in http.server (zero external dependencies beyond yt-dlp)
"""

import json
import os
import sys
import subprocess
import threading
import uuid
import time
import re
import shutil
import platform
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# --- Configuration ---
HOST = "127.0.0.1"
PORT = 19527


def _get_app_dir():
    """Find the directory containing index.html.

    Handles three scenarios:
    1. Running from source (script next to index.html)
    2. Running from PyInstaller --onefile bundle (resources unpacked to sys._MEIPASS)
    3. Running from a .app bundle (Contents/Resources/)
    """
    # PyInstaller one-file: temporary extraction dir
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    # PyInstaller one-dir / .app bundle: look near the executable
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
        # .app/Contents/MacOS/executable -> Resources lives at Contents/Resources
        candidate = os.path.join(os.path.dirname(base), "Resources")
        if os.path.exists(os.path.join(candidate, "index.html")):
            return candidate
        return base
    # Running from source
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _get_app_dir()
DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads", "YouTubeDownloader")


def _detect_proxy_macos():
    """Detect proxy by reading macOS system proxy settings via scutil."""
    try:
        out = subprocess.check_output(["scutil", "--proxy"], stderr=subprocess.DEVNULL).decode()
        if "HTTPEnable : 1" in out:
            m_proxy = re.search(r"HTTPProxy\s*:\s*([\d\.]+)", out)
            m_port = re.search(r"HTTPPort\s*:\s*(\d+)", out)
            if m_proxy and m_port:
                host = m_proxy.group(1)
                port = m_port.group(1)
                return f"http://{host}:{port}"
    except Exception:
        pass
    return None


def _detect_proxy_windows():
    """Detect proxy from Windows registry (Internet Settings)."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
        )
        proxy_enable, _ = winreg.QueryValueEx(key, "ProxyEnable")
        if proxy_enable:
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")
            winreg.CloseKey(key)
            if proxy_server:
                # ProxyServer can be "host:port" or "http=host:port;https=host:port"
                if "=" in proxy_server:
                    # Parse per-protocol entries, prefer https
                    for part in proxy_server.split(";"):
                        if part.startswith("https="):
                            val = part.split("=", 1)[1]
                            return f"http://{val}" if not val.startswith("http") else val
                    # Fallback: first entry
                    val = proxy_server.split(";")[0].split("=", 1)[-1]
                    return f"http://{val}" if not val.startswith("http") else val
                if not proxy_server.startswith("http"):
                    return f"http://{proxy_server}"
                return proxy_server
        winreg.CloseKey(key)
    except Exception:
        pass
    return None


def _detect_proxy_from_env():
    """Read proxy from environment variables."""
    return (
        os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY") or
        os.environ.get("http_proxy") or os.environ.get("HTTP_PROXY") or
        os.environ.get("ALL_PROXY") or os.environ.get("all_proxy") or ""
    )


def _detect_proxy_auto():
    """Auto-detect proxy: prefer macOS system proxy, then env vars, then scan common ports."""
    # Skip WorkBuddy's internal proxy (very high port numbers starting with 58/59...)
    def _is_workbuddy_internal(url):
        if not url:
            return False
        import re
        m = re.search(r":(\d{5,})$", url)
        if not m:
            return False
        try:
            port = int(m.group(1))
            # WorkBuddy typically uses ports in 50000-65535 range
            if 50000 <= port <= 65535:
                return True
        except Exception:
            pass
        return False

    # 1. System proxy (macOS scutil or Windows registry — most reliable)
    sys_proxy = None
    if sys.platform == "darwin":
        sys_proxy = _detect_proxy_macos()
    elif sys.platform == "win32":
        sys_proxy = _detect_proxy_windows()
    if sys_proxy and not _is_workbuddy_internal(sys_proxy):
        return sys_proxy

    # 2. Environment variables (skip WorkBuddy internal)
    env_proxy = _detect_proxy_from_env()
    if env_proxy and not _is_workbuddy_internal(env_proxy):
        return env_proxy

    # 3. Common Clash/VPN ports (fallback)
    for port in [7890, 7891, 7892, 7893, 7894, 7895, 7896, 7897, 10809, 1087]:
        try:
            import socket
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return f"http://127.0.0.1:{port}"
        except Exception:
            continue

    return ""


PROXY_URL = _detect_proxy_auto()


def _get_user_agent():
    """Return a platform-appropriate User-Agent string."""
    if sys.platform == "darwin":
        return 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    elif sys.platform == "win32":
        return 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    else:
        return 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'


USER_AGENT = _get_user_agent()

# yt-dlp and ffmpeg paths
FFMPEG_BIN = shutil.which("ffmpeg")

# Ensure download directory exists
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# --- Download State Management ---
downloads = {}  # {id: {url, title, status, progress, speed, eta, filepath, ...}}
download_lock = threading.Lock()

# --- Proxy State (can be updated at runtime) ---
proxy_state = {"url": PROXY_URL}


def _get_proxy_args():
    """Build yt-dlp proxy arguments"""
    p = proxy_state.get("url", "")
    if p:
        return ["--proxy", p]
    return []


# Common yt-dlp errors → Chinese explanation + fix
_ERROR_PATTERNS = [
    (r"Unsupported URL",          "不支持的视频链接。请确认是 YouTube、B 站、TikTok 等 yt-dlp 支持的网站链接。"),
    (r"No video formats found",   "找不到可下载的视频格式（可能是会员/付费视频，或年龄限制视频）。"),
    (r"Sign in to confirm.*bot",  "YouTube 检测到机器人。已尝试切换客户端，请重试（如果还失败，请告知）。"),
    (r"Video unavailable",        "视频不可用（已删除、设为私密、或地区限制）。"),
    (r"Private video",            "视频是私密的，无法下载。"),
    (r"HTTP Error 403",           "服务器拒绝访问（403）。可能是视频有地区限制，或需要登录账号。"),
    (r"HTTP Error 404",           "视频不存在（404）。请检查链接是否正确。"),
    (r"Unable to extract.*data",  "无法解析视频信息。YouTube 接口变动，yt-dlp 版本可能需要更新。"),
    (r"This video is unavailable","视频不可用（已删除、地区限制或需要登录）。"),
    (r"Connection refused",       "无法连接到 YouTube，请检查代理设置（右上角 ⚙️）。"),
    (r"timed out",                "连接超时，可能是网络问题。请检查代理/VPN 是否正常工作。"),
    (r"Unable to download.*format","没有匹配该画质的格式，请换其他画质重试。"),
    (r"No suitable extractor",    "yt-dlp 不支持这个视频网站。"),
    (r"EOF occurred in violation", "网络连接中断，请重试。"),
]


def _humanize_error(stderr_text):
    """Convert yt-dlp English errors to Chinese + actionable suggestions."""
    if not stderr_text:
        return ""
    text = stderr_text.strip() if isinstance(stderr_text, str) else str(stderr_text)
    # Pull out the first ERROR: line for context
    first_error = ""
    for line in text.split('\n'):
        if 'ERROR:' in line:
            first_error = line.replace('ERROR:', '').strip()
            break
    if not first_error:
        # Try to use the first non-empty line
        for line in text.split('\n'):
            line = line.strip()
            if line and not line.startswith('Traceback') and not line.startswith('  '):
                first_error = line
                break

    import re
    matched_msg = None
    for pattern, msg in _ERROR_PATTERNS:
        if re.search(pattern, first_error, re.IGNORECASE) or re.search(pattern, text, re.IGNORECASE):
            matched_msg = msg
            break

    if matched_msg:
        return f"{matched_msg}\n\n（详细错误：{first_error[:200]}）"
    elif first_error:
        return f"下载失败：{first_error[:300]}"
    else:
        last_lines = '\n'.join(text.split('\n')[-3:])[:300]
        return f"下载失败：{last_lines}"


def _format_speed(speed):
    """Format download speed in human-readable form."""
    if not speed:
        return ""
    if speed < 1024:
        return f"{speed:.0f} B/s"
    elif speed < 1024 * 1024:
        return f"{speed / 1024:.1f} KiB/s"
    else:
        return f"{speed / 1024 / 1024:.1f} MiB/s"


def _clean_part_suffix(filepath):
    """Remove .part suffix from filepath and rename the actual file if needed.

    yt-dlp creates temporary .part files during download. In some cases (e.g.
    when the download is a single pre-merged format), the 'finished' callback
    may report a filename still ending in .part. This ensures the final file
    has a clean extension.
    """
    if not filepath or not filepath.endswith('.part'):
        return filepath
    clean_path = filepath[:-5]
    try:
        if os.path.exists(filepath) and not os.path.exists(clean_path):
            os.rename(filepath, clean_path)
        elif os.path.exists(clean_path) and os.path.exists(filepath):
            # Final file already exists, remove leftover .part
            os.remove(filepath)
        return clean_path
    except Exception:
        return filepath


def _format_eta(eta):
    """Format ETA in human-readable form."""
    if eta is None or eta < 0:
        return ""
    if eta < 60:
        return f"{eta}s"
    elif eta < 3600:
        return f"{eta // 60}m{eta % 60}s"
    else:
        return f"{eta // 3600}h{(eta % 3600) // 60}m"


def get_video_info(url):
    """Fetch video metadata using yt-dlp Python API"""
    try:
        from yt_dlp import YoutubeDL

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'extractor_args': {'youtube': {'player_client': ['web', 'android']}},
            'http_headers': {
                'User-Agent': USER_AGENT,
            },
        }
        proxy = proxy_state.get('url', '')
        if proxy:
            ydl_opts['proxy'] = proxy

        with YoutubeDL(ydl_opts) as ydl:
            data = ydl.extract_info(url, download=False)

        if not data:
            return {'success': False, 'error': '无法获取视频信息'}

        # Handle playlists: take the first video
        if 'entries' in data and data['entries']:
            data = data['entries'][0]

        formats = []
        for f in data.get('formats', []):
            if not isinstance(f, dict):
                continue
            if f.get('vcodec') != 'none' or f.get('acodec') != 'none':
                formats.append({
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext'),
                    'resolution': f.get('resolution') or '',
                    'height': f.get('height') or 0,
                    'width': f.get('width') or 0,
                    'fps': f.get('fps') or 0,
                    'vcodec': f.get('vcodec') or 'none',
                    'acodec': f.get('acodec') or 'none',
                    'filesize': f.get('filesize') or f.get('filesize_approx') or 0,
                    'tbr': f.get('tbr') or 0,
                })

        quality_options = []
        seen_heights = set()
        for f in sorted(formats, key=lambda x: x.get('height', 0), reverse=True):
            h = f.get('height', 0)
            if h > 0 and h not in seen_heights:
                seen_heights.add(h)
                quality_options.append({
                    'label': f"{h}p",
                    'height': h,
                    'ext': f.get('ext', 'mp4'),
                })

        return {
            'success': True,
            'title': data.get('title', 'Unknown'),
            'uploader': data.get('uploader', data.get('channel', 'Unknown')),
            'duration': data.get('duration', 0),
            'thumbnail': data.get('thumbnail', ''),
            'view_count': data.get('view_count', 0),
            'description': (data.get('description') or '')[:500],
            'webpage_url': data.get('webpage_url', url),
            'formats': formats,
            'quality_options': quality_options,
        }
    except Exception as e:
        error_str = str(e)
        # Check for proxy/network issues
        if 'Unable to connect' in error_str or 'Connection refused' in error_str or 'timed out' in error_str.lower():
            error_str += '\n\n提示：无法连接 YouTube，请检查代理/VPN 设置（点击右上角设置按钮配置代理）'
        return {'success': False, 'error': _humanize_error(error_str)}


def start_download(url, quality, download_id):
    """Start downloading a video in a background thread using yt-dlp Python API"""
    with download_lock:
        downloads[download_id] = {
            'id': download_id,
            'url': url,
            'title': '获取中...',
            'status': 'preparing',
            'progress': 0,
            'speed': '',
            'eta': '',
            'filepath': '',
            'error': '',
            'started_at': time.time(),
        }

    def download_worker():
        try:
            from yt_dlp import YoutubeDL

            # Build format string
            if quality == 'audio':
                fmt = "bestaudio/best"
            elif quality == 'best':
                fmt = "bestvideo+bestaudio/best" if FFMPEG_BIN else "best"
            elif quality.endswith('p'):
                height = quality[:-1]
                if FFMPEG_BIN:
                    fmt = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]/best"
                else:
                    fmt = f"best[height<={height}]/best"
            else:
                fmt = "bestvideo+bestaudio/best" if FFMPEG_BIN else "best"

            output_template = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")

            def progress_hook(d):
                if d['status'] == 'downloading':
                    with download_lock:
                        downloads[download_id]['status'] = 'downloading'
                        total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                        downloaded = d.get('downloaded_bytes', 0)
                        if total > 0:
                            downloads[download_id]['progress'] = round(downloaded / total * 100, 1)
                        speed = d.get('speed')
                        if speed:
                            downloads[download_id]['speed'] = _format_speed(speed)
                        eta = d.get('eta')
                        if eta is not None:
                            downloads[download_id]['eta'] = _format_eta(eta)
                        info_dict = d.get('info_dict') or {}
                        title = info_dict.get('title')
                        if title:
                            downloads[download_id]['title'] = title
                elif d['status'] == 'finished':
                    with download_lock:
                        downloads[download_id]['progress'] = 100
                        filename = d.get('filename', '')
                        if filename:
                            downloads[download_id]['filepath'] = _clean_part_suffix(filename)

            ydl_opts = {
                'format': fmt,
                'outtmpl': output_template,
                'noplaylist': True,
                'progress_hooks': [progress_hook],
                'extractor_args': {'youtube': {'player_client': ['web', 'android']}},
                # ── Network resilience ────────────────────────────────────────
                # YouTube serves video fragments from dozens of GoogleVideo CDN
                # edge nodes (rr5---sn-*.googlevideo.com). Any single one of
                # them can be slow/unreachable on the user's route, even when
                # the proxy itself is healthy. yt-dlp's defaults (socket_timeout
                # = 20, retries suppressed for HTTPS read timeouts) cause it
                # to abort on the first hiccup. Bump these so it can hop to
                # another node automatically.
                'socket_timeout': 60,
                'retries': 10,
                'fragment_retries': 10,
                'extractor_retries': 5,
                'retry_sleep': 'http,expponential:0.5:3:2.0',
                'file_access_retries': 5,
                'force_ipv4': True,           # avoid IPv6 fallback failures on Chinese networks
                # ──────────────────────────────────────────────────────────────
                'http_headers': {
                    'User-Agent': USER_AGENT,
                },
                'quiet': True,
                'no_warnings': True,
            }

            proxy = proxy_state.get('url', '')
            if proxy:
                ydl_opts['proxy'] = proxy

            # Audio extraction to MP3
            if quality == 'audio' and FFMPEG_BIN:
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '0',
                }]

            if FFMPEG_BIN:
                ydl_opts['ffmpeg_location'] = os.path.dirname(FFMPEG_BIN)

            with YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            with download_lock:
                downloads[download_id]['status'] = 'completed'
                downloads[download_id]['progress'] = 100
                if info:
                    title = info.get('title', '')
                    if title:
                        downloads[download_id]['title'] = title
                    requested_downloads = info.get('requested_downloads', [])
                    if requested_downloads:
                        filepath = requested_downloads[0].get('filepath', '')
                        if filepath:
                            downloads[download_id]['filepath'] = _clean_part_suffix(filepath)
                    elif not downloads[download_id].get('filepath'):
                        # Fallback: construct from info
                        ext = info.get('ext', 'mp4')
                        title = info.get('title', 'video')
                        safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).strip()
                        downloads[download_id]['filepath'] = os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")

        except Exception as e:
            error_str = str(e)
            with download_lock:
                downloads[download_id]['status'] = 'error'
                downloads[download_id]['error'] = _humanize_error(error_str) or '下载失败，原因未知'

    thread = threading.Thread(target=download_worker, daemon=True)
    thread.start()


class RequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the downloader app"""

    def log_message(self, format, *args):
        pass  # Suppress console output

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _send_file(self, filepath, content_type):
        try:
            with open(filepath, 'rb') as f:
                content = f.read()
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == '/' or parsed.path == '/index.html':
            self._send_file(os.path.join(APP_DIR, 'index.html'), 'text/html; charset=utf-8')
        elif parsed.path == '/api/downloads':
            with download_lock:
                data = list(downloads.values())
            self._send_json({'success': True, 'downloads': data})
        elif parsed.path == '/api/config':
            self._send_json({
                'success': True,
                'download_dir': DOWNLOAD_DIR,
                'ffmpeg_available': FFMPEG_BIN is not None,
                'yt_dlp_version': _get_yt_dlp_version(),
                'proxy': proxy_state.get('url', ''),
                'platform': sys.platform,
            })
        elif parsed.path == '/api/open-downloads':
            _open_in_file_manager(DOWNLOAD_DIR)
            self._send_json({'success': True})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == '/api/info':
            body = self._read_body()
            if body is None:
                return
            url = body.get('url', '').strip()
            if not url:
                self._send_json({'success': False, 'error': 'URL is required'}, 400)
                return
            if not _is_valid_youtube_url(url):
                self._send_json({'success': False, 'error': 'Invalid YouTube URL'}, 400)
                return
            info = get_video_info(url)
            self._send_json(info)

        elif parsed.path == '/api/download':
            body = self._read_body()
            if body is None:
                return
            url = body.get('url', '').strip()
            quality = body.get('quality', 'best')
            if not url:
                self._send_json({'success': False, 'error': 'URL is required'}, 400)
                return
            download_id = str(uuid.uuid4())[:8]
            start_download(url, quality, download_id)
            self._send_json({'success': True, 'download_id': download_id})

        elif parsed.path == '/api/clear':
            body = self._read_body()
            if body is None:
                return
            download_id = body.get('id', '')
            with download_lock:
                if download_id in downloads:
                    if downloads[download_id].get('status') in ('completed', 'error'):
                        del downloads[download_id]
                        self._send_json({'success': True})
                    else:
                        self._send_json({'success': False, 'error': 'Cannot remove active download'}, 400)
                else:
                    self._send_json({'success': False, 'error': 'Download not found'}, 404)

        elif parsed.path == '/api/proxy':
            body = self._read_body()
            if body is None:
                return
            proxy_url = body.get('proxy', '').strip()
            proxy_state['url'] = proxy_url
            # Also update environment for subprocess inheritance
            if proxy_url:
                os.environ['http_proxy'] = proxy_url
                os.environ['https_proxy'] = proxy_url
                os.environ['HTTP_PROXY'] = proxy_url
                os.environ['HTTPS_PROXY'] = proxy_url
            else:
                for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY']:
                    os.environ.pop(key, None)
            self._send_json({'success': True, 'proxy': proxy_url})
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def _read_body(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            return json.loads(body)
        except Exception:
            self._send_json({'success': False, 'error': 'Invalid request body'}, 400)
            return None


def _is_valid_youtube_url(url):
    patterns = [
        r'(https?://)?(www\.)?youtube\.com/watch\?v=',
        r'(https?://)?(www\.)?youtu\.be/',
        r'(https?://)?(www\.)?youtube\.com/shorts/',
        r'(https?://)?(www\.)?youtube\.com/embed/',
    ]
    return any(re.match(p, url) for p in patterns)


_yt_dlp_version_cache = None
def _get_yt_dlp_version():
    global _yt_dlp_version_cache
    if _yt_dlp_version_cache:
        return _yt_dlp_version_cache
    try:
        from yt_dlp.version import __version__ as v
        _yt_dlp_version_cache = v
        return v
    except Exception:
        return "unknown"


def _is_existing_instance_alive(host=HOST, port=PORT):
    """Check if another instance of YouTubeDownloader is already listening on this port.

    We use a TCP connect (not bind) so we can reuse a port another process is holding.
    Returns True if some process is already serving on (host, port).
    """
    import socket
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _open_in_file_manager(path):
    """Open the given path in the platform's file manager."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(['open', path])
        elif sys.platform == "win32":
            subprocess.Popen(['explorer', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception:
        pass


def _focus_existing_window():
    """Bring the existing YouTubeDownloader app window to the front."""
    if sys.platform == "darwin":
        try:
            subprocess.run(
                ["osascript", "-e",
                 'try\n  tell application "YouTubeDownloader" to activate\nend try'],
                timeout=2, check=False
            )
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.FindWindowW(None, "YouTube Downloader")
            if hwnd:
                user32.ShowWindow(hwnd, 9)   # SW_RESTORE
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass


def main():
    # ---- Single-instance guard ----
    if _is_existing_instance_alive():
        print(f"ℹ️  Another instance is already running at http://{HOST}:{PORT}")
        print("   Focusing existing window instead of starting a new instance.")
        _focus_existing_window()
        return

    # Start HTTP server in a background thread.
    # pywebview MUST run on the main thread (GUI requirement on macOS; also works on Windows).
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    print(f"🎵 YouTube Downloader")
    print(f"   Server running at http://{HOST}:{PORT}")
    print(f"   Download directory: {DOWNLOAD_DIR}")
    print(f"   yt-dlp version: {_get_yt_dlp_version()}")
    print(f"   ffmpeg: {'available' if FFMPEG_BIN else 'not found (high-quality merge may fail)'}")
    print(f"   proxy: {proxy_state.get('url', 'none (direct connection)')}")

    # Launch native window via pywebview (macOS WKWebView / Windows Edge WebView2 — no browser needed)
    import webview
    window = webview.create_window(
        'YouTube Downloader',
        f'http://{HOST}:{PORT}',
        width=900,
        height=700,
        min_size=(700, 500),
        text_select=True,
    )
    webview.start()  # Blocks until the window is closed

    # Window closed → shut down the server and exit
    print("\n   Window closed, shutting down...")
    server.shutdown()


if __name__ == '__main__':
    main()
