import io
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from flask import Flask, Response, render_template, request
from werkzeug.middleware.proxy_fix import ProxyFix

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "visits.db"

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS visits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visited_at TEXT NOT NULL,
                device TEXT,
                os TEXT,
                browser TEXT,
                device_type TEXT,
                user_agent TEXT,
                ip_address TEXT
            )
            """
        )
        for column, col_type in (
            ("os", "TEXT"),
            ("browser", "TEXT"),
            ("device_type", "TEXT"),
        ):
            try:
                conn.execute(f"ALTER TABLE visits ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass


def client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("X-Real-IP", "")
    if real_ip:
        return real_ip.strip()
    return request.remote_addr or ""


def parse_client(user_agent: str) -> dict:
    ua = user_agent
    ua_lower = ua.lower()

    if "ipad" in ua_lower or "tablet" in ua_lower:
        device_type = "Tablet"
    elif "mobile" in ua_lower or "iphone" in ua_lower or "android" in ua_lower:
        device_type = "Mobile"
    else:
        device_type = "Desktop"

    if "iphone" in ua_lower:
        os = "iOS (iPhone)"
    elif "ipad" in ua_lower:
        os = "iOS (iPad)"
    elif "android" in ua_lower:
        os = "Android"
    elif "windows" in ua_lower:
        os = "Windows"
    elif "macintosh" in ua_lower or "mac os" in ua_lower:
        os = "macOS"
    elif "linux" in ua_lower:
        os = "Linux"
    else:
        os = "Unknown"

    if "edg/" in ua_lower or "edge/" in ua_lower:
        browser = "Edge"
    elif "samsungbrowser" in ua_lower:
        browser = "Samsung Internet"
    elif "firefox/" in ua_lower:
        browser = "Firefox"
    elif "opr/" in ua_lower or "opera" in ua_lower:
        browser = "Opera"
    elif "chrome/" in ua_lower or "crios/" in ua_lower:
        browser = "Chrome"
    elif "safari/" in ua_lower:
        browser = "Safari"
    else:
        browser = "Unknown"

    if "iphone" in ua_lower:
        model = "iPhone"
    elif "ipad" in ua_lower:
        model = "iPad"
    elif "android" in ua_lower:
        match = re.search(r"Android [^;]+;\s*([^)]+)\)", ua)
        model = match.group(1).strip() if match else ""
    else:
        model = ""

    device = " · ".join(part for part in (device_type, os, browser, model) if part)

    return {
        "device": device,
        "os": os,
        "browser": browser,
        "device_type": device_type,
    }


def log_visit() -> None:
    user_agent = request.headers.get("User-Agent", "")
    client = parse_client(user_agent)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO visits (
                visited_at, device, os, browser, device_type, user_agent, ip_address
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                client["device"],
                client["os"],
                client["browser"],
                client["device_type"],
                user_agent,
                client_ip(),
            ),
        )


def target_url() -> str:
    return request.url_root.rstrip("/") + "/secret"


def make_qr_image(url: str) -> bytes:
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@app.route("/")
def index():
    return render_template("index.html", target=target_url())


@app.route("/qr.png")
def qr_png():
    png = make_qr_image(target_url())
    return Response(png, mimetype="image/png")


@app.route("/secret")
def secret():
    log_visit()
    return render_template("secret.html")


def get_stats() -> dict:
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM visits").fetchone()["n"]
        by_device = conn.execute(
            """
            SELECT COALESCE(device_type, device) AS device, COUNT(*) AS count
            FROM visits
            GROUP BY COALESCE(device_type, device)
            ORDER BY count DESC
            """
        ).fetchall()
        by_browser = conn.execute(
            """
            SELECT browser, COUNT(*) AS count
            FROM visits
            WHERE browser IS NOT NULL AND browser != ''
            GROUP BY browser
            ORDER BY count DESC
            """
        ).fetchall()
        recent = conn.execute(
            """
            SELECT visited_at, device, os, browser, device_type, ip_address
            FROM visits
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()
    return {
        "total": total,
        "by_device": by_device,
        "by_browser": by_browser,
        "recent": recent,
    }


@app.route("/stats")
def stats():
    return render_template("stats.html", **get_stats())


init_db()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
