import io
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import qrcode
from flask import Flask, Response, render_template, request

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "visits.db"

app = Flask(__name__)


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
                user_agent TEXT,
                ip_address TEXT
            )
            """
        )


def log_visit() -> None:
    user_agent = request.headers.get("User-Agent", "")
    device = parse_device(user_agent)

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO visits (visited_at, device, user_agent, ip_address)
            VALUES (?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                device,
                user_agent,
                request.remote_addr or "",
            ),
        )


def parse_device(user_agent: str) -> str:
    ua = user_agent.lower()
    if "iphone" in ua or "ipad" in ua:
        return "iOS"
    if "android" in ua:
        return "Android"
    if "windows" in ua:
        return "Windows"
    if "macintosh" in ua or "mac os" in ua:
        return "macOS"
    if "linux" in ua:
        return "Linux"
    return "Unknown"


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
            SELECT device, COUNT(*) AS count
            FROM visits
            GROUP BY device
            ORDER BY count DESC
            """
        ).fetchall()
        recent = conn.execute(
            """
            SELECT visited_at, device, ip_address
            FROM visits
            ORDER BY id DESC
            LIMIT 50
            """
        ).fetchall()
    return {"total": total, "by_device": by_device, "recent": recent}


@app.route("/stats")
def stats():
    return render_template("stats.html", **get_stats())


init_db()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
