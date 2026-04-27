import argparse
import difflib
import hashlib
import html
import json
import os
import smtplib
import ssl
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_CONFIG = "config.json"


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        raw = html.unescape(" ".join(self._parts))
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line)


@dataclass(frozen=True)
class Snapshot:
    content_hash: str
    fetched_at: str
    text: str


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Nedostaje konfiguracija: {path}")
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def fetch_text(url: str, timeout_seconds: int, user_agent: str) -> str:
    request = Request(url, headers={"User-Agent": user_agent})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP greska {exc.code} pri citanju stranice.") from exc
    except URLError as exc:
        raise RuntimeError(f"Ne mogu da pristupim stranici: {exc.reason}") from exc

    parser = TextExtractor()
    parser.feed(body)
    return parser.text()


def make_snapshot(text: str) -> Snapshot:
    normalized = "\n".join(line.rstrip() for line in text.splitlines()).strip()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return Snapshot(
        content_hash=digest,
        fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        text=normalized,
    )


def load_previous(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: Path, snapshot: Snapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "content_hash": snapshot.content_hash,
        "fetched_at": snapshot.fetched_at,
        "text": snapshot.text,
    }
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def build_diff(previous_text: str, current_text: str) -> str:
    previous_lines = previous_text.splitlines()
    current_lines = current_text.splitlines()
    diff = difflib.unified_diff(
        previous_lines,
        current_lines,
        fromfile="prethodno",
        tofile="trenutno",
        lineterm="",
        n=3,
    )
    result = "\n".join(diff)
    return result[:12000] if result else "(Promena je detektovana, ali diff je prazan posle normalizacije.)"


def send_email(config: dict[str, Any], subject_suffix: str, body: str) -> None:
    email_config = config.get("email", {})
    if not email_config.get("enabled", False):
        return

    message = EmailMessage()
    message["From"] = email_config["from"]
    message["To"] = email_config["to"]
    message["Subject"] = f"{email_config.get('subject', 'Promena na sajtu')}{subject_suffix}"
    message.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(email_config["smtp_host"], int(email_config.get("smtp_port", 587))) as server:
        server.starttls(context=context)
        server.login(email_config["smtp_username"], email_config["smtp_password"])
        server.send_message(message)


def send_windows_notification(config: dict[str, Any], title_suffix: str, body: str) -> None:
    notification_config = config.get("windows_notification", {})
    if not notification_config.get("enabled", False):
        return

    title = f"{notification_config.get('title', 'Stranica je promenjena')}{title_suffix}"
    short_body = body.replace("'", "''")[:900]
    short_title = title.replace("'", "''")[:120]
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = '{short_title}'
$notify.BalloonTipText = '{short_body}'
$notify.Visible = $true
$notify.ShowBalloonTip(10000)
Start-Sleep -Seconds 12
$notify.Dispose()
"""
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def send_ntfy_notification(config: dict[str, Any], title_suffix: str, body: str) -> None:
    ntfy_config = config.get("ntfy", {})
    if not ntfy_config.get("enabled", False):
        return

    topic = ntfy_config.get("topic") or os.environ.get(ntfy_config.get("topic_env", "NTFY_TOPIC"), "")
    if not topic:
        print("ntfy je ukljucen, ali topic nije podesen.")
        return

    server = ntfy_config.get("server", "https://ntfy.sh").rstrip("/")
    title = f"{ntfy_config.get('title', 'Stranica je promenjena')}{title_suffix}"
    request = Request(
        f"{server}/{topic}",
        data=body[:4000].encode("utf-8"),
        headers={
            "Title": title[:120],
            "Tags": ntfy_config.get("tags", "warning"),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=int(ntfy_config.get("timeout_seconds", 20))):
            pass
    except (HTTPError, URLError) as exc:
        print(f"ntfy obavestenje nije poslato: {exc}")


def notify(config: dict[str, Any], title_suffix: str, body: str) -> None:
    send_windows_notification(config, title_suffix, body)
    send_ntfy_notification(config, title_suffix, body)
    send_email(config, title_suffix, body)


def run(config_path: Path, test_notification: bool) -> int:
    config = load_config(config_path)
    state_path = Path(config.get("state_file", "state.json"))
    if not state_path.is_absolute():
        state_path = config_path.parent / state_path

    if test_notification:
        notify(config, " - test", "Ovo je test poruka iz FTN site update monitora.")
        print("Test obavestenje je poslato.")
        return 0

    current = make_snapshot(
        fetch_text(
            config["url"],
            int(config.get("timeout_seconds", 30)),
            config.get("user_agent", "site-update-monitor/1.0"),
        )
    )
    previous = load_previous(state_path)

    if previous is None:
        save_state(state_path, current)
        print("Snimljeno pocetno stanje. Mejl se salje tek kada se ubuduce detektuje promena.")
        return 0

    if previous.get("content_hash") == current.content_hash:
        print(f"Nema promene. Provereno: {current.fetched_at}")
        return 0

    diff = build_diff(previous.get("text", ""), current.text)
    body = (
        "Detektovana je promena na FTN stranici.\n\n"
        f"URL: {config['url']}\n"
        f"Vreme provere UTC: {current.fetched_at}\n\n"
        "Razlika:\n"
        f"{diff}\n"
    )
    notify(config, "", body)
    save_state(state_path, current)
    print("Detektovana promena. Stanje je azurirano, a obavestenje je poslato ako je email ukljucen.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor za promene na web stranici.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Putanja do config.json fajla.")
    parser.add_argument("--test-notification", action="store_true", help="Posalji probno obavestenje i zavrsi.")
    parser.add_argument("--test-email", action="store_true", help="Stari naziv za --test-notification.")
    args = parser.parse_args()

    try:
        return run(Path(args.config).resolve(), args.test_notification or args.test_email)
    except Exception as exc:
        print(f"Greska: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
