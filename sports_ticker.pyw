"""
Sports Score Ticker for Windows  (NHL · NFL · MLB · NBA · Bundesliga · F1)
--------------------------------------------------------------------------
Version 2.9.0 (see CHANGELOG.md for the history of changes)

An always-on-top bar that scrolls every game for the day in the league you
pick. Click any game for its full stats: line score, team stats, scoring
plays, and every player's box score. Finished games get buttons that play the
highlight video from each team's official YouTube channel.

Data sources (public, no key needed):
  NHL ................. api-web.nhle.com (the NHL's own feed)
  NFL, MLB, NBA,
  Bundesliga .......... site.api.espn.com (the feed behind ESPN.com)
  F1 .................. api.jolpi.ca (Jolpica, the Ergast-compatible F1 API);
                        live race order from ESPN, or F1's official live timing
                        (livetiming.formula1.com) when signed in with an F1 account
Requires only Python 3.9+ (standard library: tkinter, urllib, json).

Controls
  League logo (left) ....... click to pick a league; drag to move the bar
  Left-click a game ........ open the game's stats window
  Hover over the ticker .... pause scrolling
  Mouse wheel .............. scroll through games by hand
  Right-click .............. settings menu (day, speed, direction, position...)
  X (far right) ............ close the ticker
"""

import base64
import copy
import hashlib
import json
import os
import queue
import re
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from tkinter import messagebox, ttk

NHL_API = "https://api-web.nhle.com/v1"
ESPN_API = "https://site.api.espn.com/apis/site/v2/sports"
JOLPICA = "https://api.jolpi.ca/ergast/f1"
APP_VERSION = "2.9.0"
USER_AGENT = f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) SportsTicker/{APP_VERSION}"

# ---------------------------------------------------------------- theme ----
BG = "#0f141c"
BG_HOVER = "#1d2633"
BG_PANEL = "#151c27"
BADGE_BG = "#f2f4f7"
FG = "#e8edf3"
FG_DIM = "#8b96a5"
FG_LOSER = "#9aa4b1"
ACCENT = "#4fa3ff"
LIVE = "#ff4d4d"
GOOD = "#5bd17a"
SEP = "#2a3442"

TICKER_HEIGHT = 51          # px at 100% display scaling
K = TICKER_HEIGHT / 34.0    # size factor for ticker fonts and spacing

# ---------------------------------------------------------------- leagues ---
ESPN_IMG = "https://a.espncdn.com/i"
LEAGUES = {
    "nhl": {"name": "NHL", "provider": "nhl", "espn": "hockey/nhl", "yt": "NHL",
            "logo": f"{ESPN_IMG}/teamlogos/leagues/500/nhl.png"},
    "nfl": {"name": "NFL", "provider": "espn", "espn": "football/nfl", "yt": "NFL",
            "logo": f"{ESPN_IMG}/teamlogos/leagues/500/nfl.png"},
    "mlb": {"name": "MLB", "provider": "espn", "espn": "baseball/mlb", "yt": "MLB",
            "logo": f"{ESPN_IMG}/teamlogos/leagues/500/mlb.png"},
    "nba": {"name": "NBA", "provider": "espn", "espn": "basketball/nba", "yt": "NBA",
            "logo": f"{ESPN_IMG}/teamlogos/leagues/500/nba.png"},
    "bun": {"name": "Bundesliga", "provider": "espn", "espn": "soccer/ger.1",
            "yt": "Bundesliga", "logo": f"{ESPN_IMG}/leaguelogos/soccer/500/10.png"},
    "f1": {"name": "F1", "provider": "f1", "espn": "racing/f1", "yt": "FORMULA 1",
           "logo": f"{ESPN_IMG}/teamlogos/leagues/500/f1.png"},
}

# F1 constructor colours (constructorId -> colour), used for the team bar.
F1_TEAM_COLORS = {
    "red_bull": "#3671C6", "ferrari": "#E8002D", "mercedes": "#27F4D2", "mclaren": "#FF8000",
    "aston_martin": "#229971", "alpine": "#00A1E8", "williams": "#64C4FF", "rb": "#6692FF",
    "racing_bulls": "#6692FF", "haas": "#B6BABD", "sauber": "#52E252", "audi": "#F50537",
    "cadillac": "#C9A94E",
}
PODIUM = {1: "#ffd166", 2: "#cfd8e3", 3: "#e0a370"}


def f1_short(name):
    return (name or "").replace("Grand Prix", "GP").strip()


def f1_start(race):
    """A race's (or session's) start as an aware datetime, from date + time."""
    if not race or not race.get("date"):
        return None
    return parse_utc(f"{race['date']}T{race.get('time') or '12:00:00Z'}")


def f1_result_text(r):
    t = (r.get("Time") or {}).get("time")
    if t:
        return t
    st = r.get("status") or ""
    if st.startswith("+") or st == "Lapped":
        return st
    return {"Disqualified": "DSQ", "Did not start": "DNS", "Withdrew": "DNS",
            "Did not qualify": "DNQ"}.get(st, "DNF")


def f1_driver(r):
    d = r.get("Driver") or {}
    return d.get("code") or (d.get("familyName") or "")[:3].upper()


def f1_full_name(d):
    return f"{d.get('givenName', '')} {d.get('familyName', '')}".strip()


F1_TEAM_MATCH = (("racing bull", "rb"), ("visa", "rb"), ("alphatauri", "rb"),
                 ("toro rosso", "rb"), ("red bull", "red_bull"), ("ferrari", "ferrari"),
                 ("mercedes", "mercedes"), ("mclaren", "mclaren"), ("aston", "aston_martin"),
                 ("alpine", "alpine"), ("williams", "williams"), ("haas", "haas"),
                 ("kick", "sauber"), ("stake", "sauber"), ("sauber", "sauber"),
                 ("audi", "audi"), ("cadillac", "cadillac"), ("andretti", "cadillac"))


def f1_color_for(team_name="", constructor_id=""):
    """A team's colour from its Jolpica constructorId or any form of its name
    (Jolpica, ESPN and F1 live timing all spell teams differently)."""
    cid = (constructor_id or "").lower()
    if cid in F1_TEAM_COLORS:
        return F1_TEAM_COLORS[cid]
    for text in (cid.replace("_", " "), (team_name or "").lower()):
        if not text:
            continue
        for key, team in F1_TEAM_MATCH:
            if key in text:
                return F1_TEAM_COLORS[team]
        if text == "rb" or text.startswith("rb "):
            return F1_TEAM_COLORS["rb"]
    return FG_DIM


def f1_team_color(r):
    con = r.get("Constructor") or {}
    return f1_color_for(con.get("name", ""), con.get("constructorId", ""))


def f1_splits(results):
    """Gap from each finisher to the car directly in front. The winner keeps
    their race time; lapped and retired cars keep their status (+1 Lap, DNF)."""
    out, prev_ms, prev_gap = [], None, 0.0
    for i, r in enumerate(results):
        t = r.get("Time") or {}
        try:
            ms = int(t.get("millis"))
        except (TypeError, ValueError):
            ms = None
        if i == 0:
            out.append(t.get("time") or f1_result_text(r))
            prev_ms, prev_gap = ms, 0.0
            continue
        gap = gap_seconds(t.get("time")) if t.get("time") else None
        if ms is not None and prev_ms is not None and ms >= prev_ms:
            out.append(f"+{(ms - prev_ms) / 1000:.3f}")
        elif gap is not None and prev_gap is not None and gap >= prev_gap:
            out.append(f"+{gap - prev_gap:.3f}")
        else:
            out.append(f1_result_text(r))
        prev_ms, prev_gap = ms, gap
    return out


# --------------------------------------------------------- live F1 timing ---
F1_TRACK_STATUS = {"2": "YELLOW FLAG", "4": "SAFETY CAR", "5": "RED FLAG",
                   "6": "VIRTUAL SAFETY CAR", "7": "VSC ENDING"}


def deep_merge(dst, src):
    """Apply a live-timing delta (nested dicts; lists patched by index)."""
    if isinstance(dst, dict) and isinstance(src, dict):
        for k, v in src.items():
            if k == "_deleted":
                for key in v if isinstance(v, list) else []:
                    dst.pop(str(key), None)
                continue
            if k in dst and isinstance(dst[k], (dict, list)) and isinstance(v, (dict, list)):
                dst[k] = deep_merge(dst[k], v)
            else:
                dst[k] = v
        return dst
    if isinstance(dst, list) and isinstance(src, dict):
        for k, v in src.items():
            try:
                i = int(k)
            except ValueError:
                continue
            while len(dst) <= i:
                dst.append({})
            dst[i] = deep_merge(dst[i], v) if isinstance(dst[i], (dict, list)) and \
                isinstance(v, (dict, list)) else v
        return dst
    return src


def extract_f1_token(text):
    """Accept the F1 'login-session' cookie value (URL-encoded JSON), the JSON
    itself, or a bare token, and return the subscription token."""
    t = (text or "").strip().strip('"')
    if "%7B" in t or "%22" in t:
        t = urllib.parse.unquote(t)
    m = re.search(r'"subscriptionToken"\s*:\s*"([^"]+)"', t)
    if m:
        return m.group(1)
    if t.lower().startswith("bearer "):
        t = t[7:].strip()
    if re.fullmatch(r"[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", t):
        return t
    return ""


def jwt_expiry(token):
    try:
        part = token.split(".")[1]
        part += "=" * (-len(part) % 4)
        exp = json.loads(base64.urlsafe_b64decode(part)).get("exp")
        return datetime.fromtimestamp(int(exp), tz=timezone.utc) if exp else None
    except Exception:
        return None


def gap_seconds(v):
    """'+4.128' -> 4.128; '' / LEADER -> 0.0; lapped or unknown -> None."""
    if v in (None, "") or str(v).upper() in ("LEADER", "LAP", "-"):
        return 0.0 if v in (None, "") or str(v).upper() in ("LEADER", "-") else None
    s_ = str(v).strip().lstrip("+")
    if "L" in s_.upper():
        return None
    try:
        if ":" in s_:
            parts = [float(x) for x in s_.split(":")]
            sec = 0.0
            for x in parts:
                sec = sec * 60 + x
            return sec
        return float(s_)
    except ValueError:
        return None


def fill_intervals(rows):
    """Give every car a split to the car ahead, deriving it from the gaps to the
    leader when the feed doesn't send intervals directly."""
    prev = None
    for i, r in enumerate(rows):
        if i == 0:
            r["interval"] = "LEADER"
            r["gap"] = r.get("gap") if r.get("gap") not in ("", None, "0", "0.000") else ""
            prev = 0.0
            continue
        g = gap_seconds(r.get("gap"))
        if not r.get("interval"):
            if g is not None and prev is not None and g >= prev and g > 0:
                r["interval"] = f"+{g - prev:.3f}"
            elif r.get("gap") and str(r["gap"]).upper().endswith(("L", "LAP", "LAPS")):
                r["interval"] = str(r["gap"])
        prev = g
    return rows


def f1_rows_from_timing(state):
    """Turn F1 live-timing state (TimingData, DriverList...) into ticker rows."""
    lines = (state.get("TimingData") or {}).get("Lines") or {}
    drivers = state.get("DriverList") or {}
    rows = []
    for num, ln in lines.items():
        if not isinstance(ln, dict):
            continue
        d = drivers.get(num) or {}
        try:
            pos = int(ln.get("Position") or ln.get("Line") or d.get("Line") or 99)
        except (TypeError, ValueError):
            pos = 99
        gap = ln.get("GapToLeader")
        gap = gap.get("Value") if isinstance(gap, dict) else gap
        iv = ln.get("IntervalToPositionAhead")
        iv = iv.get("Value") if isinstance(iv, dict) else iv
        status = "OUT" if ln.get("Retired") or ln.get("Stopped") else \
            "PIT" if ln.get("InPit") else ""
        team = d.get("TeamName", "")
        rows.append({"pos": pos, "num": str(num), "code": d.get("Tla") or str(num),
                     "name": (d.get("FullName") or "").title(), "team": team,
                     "color": ("#" + d["TeamColour"].lstrip("#")) if d.get("TeamColour")
                     else f1_color_for(team),
                     "gap": gap or "", "interval": iv or "",
                     "laps": ln.get("NumberOfLaps", ""), "pits": ln.get("NumberOfPitStops", ""),
                     "status": status})
    rows.sort(key=lambda r: r["pos"])
    lap = state.get("LapCount") or {}
    ts = state.get("TrackStatus") or {}
    info = state.get("SessionInfo") or {}
    return {"rows": rows,
            "lap": f"{lap.get('CurrentLap')}/{lap.get('TotalLaps')}" if lap.get("CurrentLap") else "",
            "track": F1_TRACK_STATUS.get(str(ts.get("Status")), ""),
            "session": info.get("Name") or info.get("Type") or "",
            "finished": (state.get("SessionStatus") or {}).get("Status") in ("Finished", "Finalised",
                                                                             "Ends")}


def _espn_stat(c, names):
    """Find a value in an ESPN competitor by any of several field/stat names."""
    want = {n.lower() for n in names}
    for k, v in c.items():
        if k.lower() in want and not isinstance(v, (dict, list)):
            return str(v)
    for st in c.get("statistics") or []:
        if not isinstance(st, dict):
            continue
        keys = {str(st.get(x, "")).lower() for x in ("name", "abbreviation", "shortDisplayName")}
        if keys & want:
            return str(st.get("displayValue") or st.get("value") or "")
    return ""


def espn_f1_live(data):
    """Running order of an in-progress F1 session from ESPN's racing feed."""
    for ev in data.get("events") or []:
        for comp in ev.get("competitions") or []:
            st = ((comp.get("status") or {}).get("type") or {})
            if st.get("state") != "in":
                continue
            typ = comp.get("type") or {}
            rows = []
            for c in comp.get("competitors") or []:
                ath = c.get("athlete") or {}
                last = ath.get("lastName") or (ath.get("displayName") or "").split(" ")[-1]
                code = ath.get("abbreviation") or last[:3].upper()
                team = ((c.get("vehicle") or {}).get("manufacturer") or
                        (c.get("team") or {}).get("displayName") or "")
                try:
                    pos = int(c.get("order") or 99)
                except (TypeError, ValueError):
                    pos = 99
                rows.append({"pos": pos, "num": str((c.get("vehicle") or {}).get("number", "")),
                             "code": code, "name": ath.get("displayName", ""), "team": team,
                             "color": f1_color_for(team, str((c.get("team") or {}).get("abbreviation", ""))),
                             "gap": _espn_stat(c, ("behind", "gapToLeader", "behindLeader",
                                                   "timeBehind", "gap", "totalTime", "time")),
                             "interval": _espn_stat(c, ("interval", "behindNext", "gapToNext",
                                                        "intervalToPositionAhead")),
                             "laps": _espn_stat(c, ("laps", "lapsCompleted")),
                             "pits": _espn_stat(c, ("pitStops", "pits")), "status": ""})
            rows.sort(key=lambda r: r["pos"])
            # Total race times instead of gaps? Convert to gaps to the leader.
            if rows and ":" in str(rows[0]["gap"]):
                lead = gap_seconds(rows[0]["gap"])
                for r in rows:
                    g = gap_seconds(r["gap"])
                    r["gap"] = "" if r is rows[0] else (f"+{g - lead:.3f}" if g is not None and
                                                         lead is not None else r["gap"])
            per = (comp.get("status") or {}).get("period")
            return {"rows": rows, "lap": str(per) if per else "",
                    "track": "", "session": typ.get("abbreviation") or typ.get("text") or "",
                    "finished": False}
    return None


class F1AuthError(Exception):
    pass


class F1LiveTiming:
    """Minimal SignalR Core client (JSON protocol over a WebSocket, standard
    library only) for F1's official live timing. Runs on its own thread and
    keeps the merged live state; the UI reads snapshots."""

    TOPICS = ["TimingData", "DriverList", "LapCount", "SessionInfo", "SessionStatus",
              "TrackStatus"]

    def __init__(self, token, host="livetiming.formula1.com", secure=True, port=None):
        self.token, self.host, self.secure = token, host, secure
        self.port = port or (443 if secure else 80)
        self.state = {}
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.status = "Connecting to F1 live timing…"
        self.auth_failed = False
        self._stop = threading.Event()
        self.sock = None
        self._buf = b""
        self._frag, self._frag_op = [], None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()
        return self

    def stop(self):
        self._stop.set()
        try:
            if self.sock:
                self.sock.close()
        except OSError:
            pass

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.state)

    # -- connection loop --
    def _run(self):
        delay = 5
        while not self._stop.is_set():
            try:
                self._session()
                delay = 5
            except F1AuthError as e:
                if self.token:
                    # Sign-in rejected or expired: carry on with the free feed.
                    self.auth_failed = True
                    self.token = ""
                    self.status = f"F1 sign-in was rejected ({e}); using free live timing."
                    continue
                self.status = f"F1 live timing refused the connection ({e})."
                self._stop.wait(120)
                continue
            except Exception as e:  # noqa: BLE001
                if self._stop.is_set():
                    break
                self.status = f"Reconnecting to F1 live timing… ({e.__class__.__name__})"
            finally:
                try:
                    if self.sock:
                        self.sock.close()
                except OSError:
                    pass
            self._stop.wait(delay)
            delay = min(delay * 2, 60)

    def _negotiate(self):
        scheme = "https" if self.secure else "http"
        url = f"{scheme}://{self.host}:{self.port}/signalrcore/negotiate?negotiateVersion=1"
        hdrs = {"User-Agent": BROWSER_UA, "Content-Type": "text/plain;charset=UTF-8"}
        if self.token:
            hdrs["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=b"", method="POST", headers=hdrs)
        try:
            resp = urllib.request.urlopen(req, timeout=15)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise F1AuthError(f"HTTP {e.code}")
            raise
        body = json.loads(resp.read().decode("utf-8") or "{}")
        cookies = "; ".join(c.split(";", 1)[0] for c in resp.headers.get_all("Set-Cookie") or [])
        return body.get("connectionToken") or body.get("connectionId") or "", cookies

    def _session(self):
        conn, cookies = self._negotiate()
        raw = socket.create_connection((self.host, self.port), timeout=20)
        self.sock = ssl.create_default_context().wrap_socket(raw, server_hostname=self.host) \
            if self.secure else raw
        self._buf, self._frag, self._frag_op = b"", [], None
        key = base64.b64encode(os.urandom(16)).decode()
        path = "/signalrcore?id=" + urllib.parse.quote(conn, safe="")
        head = [f"GET {path} HTTP/1.1", f"Host: {self.host}", "Upgrade: websocket",
                "Connection: Upgrade", f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13",
                f"User-Agent: {BROWSER_UA}", "Origin: https://www.formula1.com"]
        if self.token:
            head.append(f"Authorization: Bearer {self.token}")
        if cookies:
            head.append(f"Cookie: {cookies}")
        self.sock.sendall(("\r\n".join(head) + "\r\n\r\n").encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("closed during handshake")
            resp += chunk
        top, self._buf = resp.split(b"\r\n\r\n", 1)
        status_line = top.split(b"\r\n")[0].decode("latin-1")
        if " 101" not in status_line:
            if " 401" in status_line or " 403" in status_line:
                raise F1AuthError(status_line.split(" ", 1)[-1])
            raise ConnectionError(status_line)
        self._send_text('{"protocol":"json","version":1}\x1e')
        self._send_text(json.dumps({"type": 1, "invocationId": "1", "target": "Subscribe",
                                    "arguments": [self.TOPICS]}) + "\x1e")
        self.status = "Connected to F1 live timing — waiting for data"
        self.sock.settimeout(5)
        last_ping, pending = time.time(), ""
        while not self._stop.is_set():
            if time.time() - last_ping > 15:
                self._send_text('{"type":6}\x1e')
                last_ping = time.time()
            try:
                op, payload = self._recv_message()
            except socket.timeout:
                continue
            if op == 8:
                raise ConnectionError("server closed the connection")
            if op == 9:
                self._send_frame(10, payload)
                continue
            if op != 1:
                continue
            pending += payload.decode("utf-8", "replace")
            *msgs, pending = pending.split("\x1e")
            for m in msgs:
                if m.strip():
                    self._handle(json.loads(m))

    def _handle(self, msg):
        t = msg.get("type")
        if t is None and msg.get("error"):
            raise ConnectionError(msg["error"])
        if t == 3:
            if msg.get("error"):
                err = str(msg["error"])
                if "auth" in err.lower() or "401" in err:
                    raise F1AuthError(err)
                self.status = f"F1 live timing refused the subscription: {err}"
                return
            if isinstance(msg.get("result"), dict):
                with self.lock:
                    for k, v in msg["result"].items():
                        self.state[k] = v
                self.status = "Live"
        elif t == 1 and msg.get("target") == "feed":
            args = msg.get("arguments") or []
            if len(args) >= 2:
                topic, data = args[0], args[1]
                with self.lock:
                    if isinstance(data, dict):
                        self.state[topic] = deep_merge(self.state.get(topic) or {}, data)
                    else:
                        self.state[topic] = data
                self.status = "Live"
        elif t == 7:
            raise ConnectionError(msg.get("error") or "server closed the connection")

    # -- WebSocket framing --
    def _send_frame(self, op, payload):
        n = len(payload)
        mask = os.urandom(4)
        hdr = bytes([0x80 | op])
        if n < 126:
            hdr += bytes([0x80 | n])
        elif n < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self.send_lock:
            self.sock.sendall(hdr + mask + body)

    def _send_text(self, text):
        self._send_frame(1, text.encode("utf-8"))

    def _parse_frame(self):
        b = self._buf
        if len(b) < 2:
            return None
        fin, op = b[0] & 0x80, b[0] & 0x0F
        masked, ln, i = b[1] & 0x80, b[1] & 0x7F, 2
        if ln == 126:
            if len(b) < 4:
                return None
            ln, i = struct.unpack(">H", b[2:4])[0], 4
        elif ln == 127:
            if len(b) < 10:
                return None
            ln, i = struct.unpack(">Q", b[2:10])[0], 10
        mask = b""
        if masked:
            if len(b) < i + 4:
                return None
            mask, i = b[i:i + 4], i + 4
        if len(b) < i + ln:
            return None
        payload = b[i:i + ln]
        if masked:
            payload = bytes(c ^ mask[j % 4] for j, c in enumerate(payload))
        self._buf = b[i + ln:]
        return bool(fin), op, payload

    def _recv_message(self):
        """Next complete message (control frames returned immediately). A
        socket timeout never loses data: nothing is consumed until a whole
        frame has arrived."""
        while True:
            f = self._parse_frame()
            if f is None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise ConnectionError("connection closed")
                self._buf += chunk
                continue
            fin, op, payload = f
            if op >= 8:
                return op, payload
            if op != 0:
                self._frag_op, self._frag = op, []
            self._frag.append(payload)
            if fin:
                data, op_ = b"".join(self._frag), self._frag_op
                self._frag, self._frag_op = [], None
                return op_, data

NHL_TEAM_COLORS = {
    "ANA": "#F47A38", "BOS": "#FFB81C", "BUF": "#2E6BD1", "CGY": "#C8102E",
    "CAR": "#CE1126", "CHI": "#CF0A2C", "COL": "#8A2E4D", "CBJ": "#2B5CA8",
    "DAL": "#00A35A", "DET": "#CE1126", "EDM": "#FF4C00", "FLA": "#C8102E",
    "LAK": "#A2AAAD", "MIN": "#2E8B57", "MTL": "#AF1E2D", "NSH": "#FFB81C",
    "NJD": "#CE1126", "NYI": "#F47D30", "NYR": "#2F6FDB", "OTT": "#C52032",
    "PHI": "#F74902", "PIT": "#FCB514", "SJS": "#00A3AD", "SEA": "#99D9D9",
    "STL": "#3B6FD8", "TBL": "#3A6FD0", "TOR": "#3D6FD6", "UTA": "#71AFE5",
    "VAN": "#00843D", "VGK": "#B4975A", "WSH": "#C8102E", "WPG": "#5B8FD6",
}
NHL_TEAM_NAMES = {
    "ANA": "Anaheim Ducks", "BOS": "Boston Bruins", "BUF": "Buffalo Sabres",
    "CGY": "Calgary Flames", "CAR": "Carolina Hurricanes", "CHI": "Chicago Blackhawks",
    "COL": "Colorado Avalanche", "CBJ": "Columbus Blue Jackets", "DAL": "Dallas Stars",
    "DET": "Detroit Red Wings", "EDM": "Edmonton Oilers", "FLA": "Florida Panthers",
    "LAK": "Los Angeles Kings", "MIN": "Minnesota Wild", "MTL": "Montreal Canadiens",
    "NSH": "Nashville Predators", "NJD": "New Jersey Devils", "NYI": "New York Islanders",
    "NYR": "New York Rangers", "OTT": "Ottawa Senators", "PHI": "Philadelphia Flyers",
    "PIT": "Pittsburgh Penguins", "SJS": "San Jose Sharks", "SEA": "Seattle Kraken",
    "STL": "St. Louis Blues", "TBL": "Tampa Bay Lightning", "TOR": "Toronto Maple Leafs",
    "UTA": "Utah Mammoth", "VAN": "Vancouver Canucks", "VGK": "Vegas Golden Knights",
    "WSH": "Washington Capitals", "WPG": "Winnipeg Jets",
}
NHL_TO_ESPN = {"LAK": "la", "NJD": "nj", "SJS": "sj", "TBL": "tb", "UTA": "utah"}
TWO_WORD_NICKS = {"Maple Leafs", "Red Wings", "Blue Jackets", "Golden Knights",
                  "Red Sox", "White Sox", "Blue Jays", "Trail Blazers"}

CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "SportsTicker")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
DEFAULT_CONFIG = {"league": "nhl", "position": "top", "y": None, "speed": 2, "scroll": True,
                  "topmost": True, "direction": "ltr", "reserve": True, "yt_channels": {},
                  "f1_token": ""}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    if cfg.get("league") not in LEAGUES:
        cfg["league"] = "nhl"
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


# ------------------------------------------------------------------ utils ---
def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.read()


def txt(v, default=""):
    """API strings are often {'default': 'Name'}; unwrap them."""
    if v is None:
        return default
    if isinstance(v, dict):
        return v.get("default") or next(iter(v.values()), default)
    return str(v)


def person(p):
    if not p:
        return ""
    if isinstance(p, str):
        return p
    if "default" in p:
        return txt(p)
    if p.get("name"):
        return txt(p.get("name"))
    first, last = txt(p.get("firstName")), txt(p.get("lastName"))
    if first and last:
        return f"{first[0]}. {last}"
    return last or first


def ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def parse_utc(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def local_time(utc_str):
    dt = parse_utc(utc_str)
    return dt.astimezone().strftime("%I:%M %p").lstrip("0") if dt else ""


def local_day(utc_str):
    dt = parse_utc(utc_str)
    if not dt:
        return ""
    dt = dt.astimezone()
    return dt.strftime("%a %b ") + str(dt.day)


def toi_seconds(v):
    try:
        m, s = str(v).split(":")
        return int(m) * 60 + int(s)
    except Exception:
        return -1


def fmt_pct(v, as_percent=True):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "" if v is None else str(v)
    if as_percent:
        return f"{f * 100:.1f}%" if f <= 1 else f"{f:.1f}%"
    return f"{f:.3f}".lstrip("0") if f < 1 else f"{f:.3f}"


def readable_color(hexstr, alt=None):
    """ESPN team colors can be near-black; pick something visible on dark bg."""
    def lum(h):
        try:
            h = h.lstrip("#")
            r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        except Exception:
            return 0
    for c in (hexstr, alt):
        if c and lum(c) > 0.18:
            return "#" + c.lstrip("#")
    return "#8b96a5"


def nickname_from(full):
    words = (full or "").split()
    if not words:
        return ""
    two = " ".join(words[-2:])
    return two if two in TWO_WORD_NICKS else words[-1]


# ---------------------------------------------------------- normalization ---
# Every game, whatever the league, becomes:
#   {"league", "id", "kind": live/final/future/ppd, "status", "start",
#    "away": TEAM, "home": TEAM, "raw"}
#   TEAM = {"abbrev", "name", "short", "score", "color", "logo", "extra"}

def nhl_period_label(pd):
    if not pd:
        return ""
    ptype = pd.get("periodType", "REG")
    num = pd.get("number") or 0
    if ptype == "OT":
        extra = num - 3
        return "OT" if extra <= 1 else f"{extra}OT"
    if ptype == "SO":
        return "SO"
    return ordinal(num)


def nhl_status(g):
    sched = g.get("gameScheduleState", "OK")
    if sched in ("PPD", "SUSP"):
        return ("Postponed" if sched == "PPD" else "Suspended"), "ppd"
    if sched == "CNCL":
        return "Cancelled", "ppd"
    state = g.get("gameState", "FUT")
    pd = g.get("periodDescriptor") or {}
    if state in ("FINAL", "OFF"):
        lab = nhl_period_label(pd)
        return ("Final/" + lab if lab in ("OT", "SO") or lab.endswith("OT") else "Final"), "final"
    if state in ("LIVE", "CRIT"):
        clock = g.get("clock") or {}
        lab = nhl_period_label(pd)
        if clock.get("inIntermission"):
            return f"{lab} INT", "live"
        if pd.get("periodType") == "SO":
            return "Shootout", "live"
        tr = clock.get("timeRemaining", "")
        return (f"{lab} {tr}".strip() or "Live"), "live"
    if state == "PRE":
        return "Pregame", "future"
    return local_time(g.get("startTimeUTC", "")) or "TBD", "future"


def nhl_team(t):
    ab = t.get("abbrev", "")
    full = NHL_TEAM_NAMES.get(ab) or txt(t.get("name")) or " ".join(
        x for x in (txt(t.get("placeName")), txt(t.get("commonName"))) if x) or ab
    code = NHL_TO_ESPN.get(ab, ab.lower())
    return {"abbrev": ab, "name": full, "short": nickname_from(full), "score": t.get("score"),
            "color": NHL_TEAM_COLORS.get(ab, FG_DIM),
            "logo": f"{ESPN_IMG}/teamlogos/nhl/500/{code}.png" if ab else "",
            "extra": f"SOG: {t['sog']}" if t.get("sog") is not None else ""}


def nhl_normalize(g):
    status, kind = nhl_status(g)
    return {"league": "nhl", "id": g.get("id"), "kind": kind, "status": status,
            "start": g.get("startTimeUTC", ""), "away": nhl_team(g.get("awayTeam", {})),
            "home": nhl_team(g.get("homeTeam", {})), "raw": g,
            "venue": txt(g.get("venue")),
            "tv": sorted({b.get("network", "") for b in g.get("tvBroadcasts") or []
                          if b.get("network")})}


def espn_status(comp, ev=None):
    st = comp.get("status") or (ev or {}).get("status") or {}
    t = st.get("type") or {}
    name = t.get("name", "")
    state = t.get("state", "pre")
    short = t.get("shortDetail") or t.get("detail") or t.get("description") or ""
    if any(x in name for x in ("POSTPONED", "CANCELED", "CANCELLED", "SUSPENDED", "DELAYED",
                               "FORFEIT")):
        return short or "Postponed", "ppd"
    if state == "post":
        return short or "Final", "final"
    if state == "in":
        return short or "Live", "live"
    when = comp.get("date") or (ev or {}).get("date", "")
    return local_time(when) or short or "TBD", "future"


def espn_team(c):
    t = c.get("team") or {}
    logo = t.get("logo") or ""
    if not logo:
        for lg in t.get("logos") or []:
            if lg.get("href"):
                logo = lg["href"]
                break
    full = t.get("displayName") or t.get("name") or t.get("abbreviation", "")
    rec = ""
    for r in c.get("records") or c.get("record") or []:
        if isinstance(r, dict) and r.get("summary"):
            rec = r["summary"]
            break
    score = c.get("score")
    if isinstance(score, dict):
        score = score.get("displayValue") or score.get("value")
    return {"abbrev": t.get("abbreviation", "") or full[:3].upper(), "name": full,
            "short": t.get("shortDisplayName") or nickname_from(full),
            "score": score if score not in (None, "") else None,
            "color": readable_color(t.get("color", ""), t.get("alternateColor")),
            "logo": logo, "extra": f"Record {rec}" if rec else "", "id": str(t.get("id", ""))}


def espn_broadcasts(comp):
    names = set()
    for b in comp.get("broadcasts") or []:
        for n in b.get("names") or []:
            names.add(n)
        m = (b.get("media") or {}).get("shortName")
        if m:
            names.add(m)
    for b in comp.get("geoBroadcasts") or []:
        m = (b.get("media") or {}).get("shortName")
        if m:
            names.add(m)
    return sorted(names)


def espn_normalize(ev, league, comp=None):
    comp = comp or (ev.get("competitions") or [{}])[0]
    cs = comp.get("competitors") or []
    away = next((c for c in cs if c.get("homeAway") == "away"), cs[0] if cs else {})
    home = next((c for c in cs if c.get("homeAway") == "home"), cs[-1] if cs else {})
    status, kind = espn_status(comp, ev)
    return {"league": league, "id": str(ev.get("id") or comp.get("id") or ""), "kind": kind,
            "status": status, "start": comp.get("date") or ev.get("date", ""),
            "away": espn_team(away), "home": espn_team(home), "raw": ev,
            "venue": (comp.get("venue") or {}).get("fullName", ""),
            "tv": espn_broadcasts(comp)}


def next_game_day(data, league, shown):
    """The next date with games after `shown` (YYYY-MM-DD), if the feed says."""
    later = []
    if LEAGUES[league]["provider"] == "nhl":
        for d in data.get("gameWeek") or []:
            if d.get("numberOfGames") and str(d.get("date", "")) > shown:
                later.append(str(d["date"])[:10])
    else:
        for lg in data.get("leagues") or []:
            if lg.get("calendarIsWhitelist") is False:
                continue          # calendar lists days *without* games
            for item in lg.get("calendar") or []:
                if isinstance(item, str):
                    day = item[:10]
                elif isinstance(item, dict):
                    if league == "nfl":
                        continue      # NFL calendar lists weeks, not game days
                    day = str(item.get("startDate") or item.get("value") or "")[:10]
                else:
                    continue
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and day > shown:
                    later.append(day)
    if not later:
        return None
    try:
        return datetime.strptime(min(later), "%Y-%m-%d")
    except ValueError:
        return None


# ------------------------------------------------------- background work ----
class Worker:
    """Runs blocking HTTP calls off the UI thread and hands results back."""

    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self._poll()

    def run(self, fn, on_done, on_error=None):
        def target():
            try:
                res = fn()
                self.q.put((on_done, res))
            except Exception as e:  # noqa: BLE001
                if on_error:
                    self.q.put((on_error, e))
        threading.Thread(target=target, daemon=True).start()

    def _poll(self):
        try:
            while True:
                cb, val = self.q.get_nowait()
                try:
                    cb(val)
                except tk.TclError:
                    pass  # window closed meanwhile
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


# ------------------------------------------------------------------ logos ---
class Logos:
    """Downloads team and league logos (PNG) in the background, caches them on
    disk, and hands back Tk images scaled to the size asked for."""

    def __init__(self, worker):
        self.worker = worker
        self.mem = {}        # (url, size, dark) -> PhotoImage, or None if unavailable
        self.waiting = {}    # key -> [callbacks]
        self.dir = os.path.join(CONFIG_DIR, "logos")

    def get(self, url, size, cb=None, dark=True):
        if not url:
            return None
        key = (url, int(size), dark)
        if key in self.mem:
            return self.mem[key]
        first = key not in self.waiting
        self.waiting.setdefault(key, [])
        if cb:
            self.waiting[key].append(cb)
        if first:
            self.worker.run(lambda: self._download(url, int(size), dark),
                            lambda data: self._loaded(key, data),
                            lambda e: self._loaded(key, None))
        return None

    @staticmethod
    def _candidates(url, size, dark):
        out = []
        m = re.match(r"https?://a\d?\.espncdn\.com(/i/.+)", url)
        if m:
            path = m.group(1)
            paths = []
            if dark:
                d = re.sub(r"/500/(scoreboard/)?", "/500-dark/", path, count=1)
                if d != path:
                    paths.append(d)
            paths.append(path)
            for p in paths:
                out.append(f"https://a.espncdn.com/combiner/i?img={p}&w={size}&h={size}")
            out.append(url)
        else:
            out.append(url)
        return out

    def _download(self, url, size, dark):
        name = hashlib.sha1(f"{url}|{size}|{dark}".encode()).hexdigest() + ".png"
        path = os.path.join(self.dir, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
        last = None
        for u in self._candidates(url, size, dark):
            try:
                data = fetch_bytes(u)
                if data[:8] == b"\x89PNG\r\n\x1a\n":
                    try:
                        os.makedirs(self.dir, exist_ok=True)
                        with open(path, "wb") as f:
                            f.write(data)
                    except OSError:
                        pass
                    return data
            except Exception as e:  # noqa: BLE001
                last = e
        raise last or IOError("no logo")

    def _loaded(self, key, data):
        img = None
        if data:
            try:
                img = tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))
                big = max(img.width(), img.height())
                if big > key[1] * 1.4:
                    f = max(1, round(big / key[1]))
                    img = img.subsample(f, f)
            except tk.TclError:
                img = None
        self.mem[key] = img
        for cb in self.waiting.pop(key, []):
            try:
                cb()
            except tk.TclError:
                pass


# ----------------------------------------------- highlight video finder ----
YT = "https://www.youtube.com"
BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def http_text(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9",
        "Cookie": "CONSENT=YES+1; SOCS=CAI"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        return resp.read().decode("utf-8", "replace")


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def yt_initial_data(html):
    m = re.search(r"(?:var ytInitialData|window\[\"ytInitialData\"\])\s*=\s*", html)
    if not m:
        return {}
    data, _ = json.JSONDecoder().raw_decode(html, m.end())
    return data


def walk(o, key):
    """Yield every dict stored under `key` anywhere in a nested JSON blob."""
    stack = [o]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if k == key and isinstance(v, dict):
                    yield v
                stack.append(v)
        elif isinstance(cur, list):
            stack.extend(reversed(cur))


def runs_text(v):
    if not isinstance(v, dict):
        return ""
    return v.get("simpleText") or "".join(r.get("text", "") for r in v.get("runs", []))


def highlights_search_url(info):
    start = info.get("start")
    day = ""
    if start:
        d = start.astimezone()
        day = f"{d.strftime('%B')} {d.day}, {d.year}"
    q = info.get("query") or f"{info['full']} highlights vs {info['opp_full']} {day}".strip()
    url = f"{YT}/results?search_query=" + urllib.parse.quote_plus(q)
    if start and (datetime.now(start.tzinfo) - start).days < 6:
        url += "&sp=EgIIAw%3D%3D"   # upload date: this week
    return url


def find_team_channel(full_name, nick):
    """Return the channel ID (UC...) of the team's official YouTube channel."""
    q = urllib.parse.quote_plus(full_name)
    data = yt_initial_data(http_text(f"{YT}/results?search_query={q}&sp=EgIQAg%3D%3D"))
    want, nick_n = norm(full_name), norm(nick)
    fallback = None
    for ch in walk(data, "channelRenderer"):
        title, cid = norm(runs_text(ch.get("title"))), ch.get("channelId")
        if not cid:
            continue
        if title == want:
            return cid
        if fallback is None and nick_n and nick_n in title and len(title) <= len(want) + 6:
            fallback = cid
    return fallback


def channel_recent_videos(cid):
    """Latest ~15 uploads from the channel's public RSS feed."""
    root = ET.fromstring(http_text(f"{YT}/feeds/videos.xml?channel_id={cid}"))
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    out = []
    for e in root.findall("a:entry", ns):
        vid = e.findtext("yt:videoId", default="", namespaces=ns)
        title = e.findtext("a:title", default="", namespaces=ns)
        pub = parse_utc(e.findtext("a:published", default="", namespaces=ns))
        if vid:
            out.append((vid, title, pub))
    return out


def score_title(title, opp_words):
    t = title.lower()
    s = 0
    if "highlight" in t or "recap" in t:
        s += 2
    if any(w and w.lower() in t for w in opp_words):
        s += 1
    return s


def pick_highlight(videos, opp_words, start):
    best = None
    for vid, title, pub in videos:
        if start and pub and pub < start:
            continue          # uploaded before kickoff: not this game
        sc = score_title(title, opp_words)
        if sc >= 2 and (best is None or sc > best[0]):
            best = (sc, vid)
    return best[1] if best else None


def search_owned_video(query, owner_names, opp_words):
    q = urllib.parse.quote_plus(query)
    data = yt_initial_data(http_text(f"{YT}/results?search_query={q}&sp=EgIIAw%3D%3D"))
    owners = {norm(o) for o in owner_names}
    for v in walk(data, "videoRenderer"):
        owner = norm(runs_text(v.get("ownerText")) or runs_text(v.get("longBylineText")))
        title = runs_text(v.get("title"))
        if v.get("videoId") and owner in owners and score_title(title, opp_words) >= 2:
            return v["videoId"]
    return None


def highlight_info(game, side):
    me, opp = game[side], game["home" if side == "away" else "away"]
    return {"key": f"{game['league']}:{me['abbrev']}", "full": me["name"], "nick": me["short"],
            "opp_full": opp["name"], "opp_words": [opp["short"], opp["abbrev"],
                                                   (opp["name"].split() or [""])[0]],
            "start": parse_utc(game.get("start")),
            "league_channel": LEAGUES[game["league"]]["yt"]}


def find_highlight_video(info, channel_cache):
    """Locate a game's highlight video. Returns (url, source description).

    1. The team's official channel: newest upload after kickoff titled
       "highlights"/"recap", preferring titles naming the opponent.
    2. A YouTube search limited to videos from that team's channel.
    3. The same, from the league's official channel.
    Falls back to a YouTube search page if none of that works.
    """
    start, day = info["start"], ""
    if start:
        d = start.astimezone()
        day = f"{d.strftime('%B')} {d.day}"
    vid, source = None, ""
    try:
        cid = channel_cache.get(info["key"]) or find_team_channel(info["full"], info["nick"])
        if cid:
            channel_cache[info["key"]] = cid
            vid = pick_highlight(channel_recent_videos(cid), info["opp_words"], start)
            source = f"{info['full']} channel"
    except Exception:
        pass
    for owners, label in (([info["full"]], f"{info['full']} channel"),
                          ([info["league_channel"]], f"{info['league_channel']} channel")):
        if vid:
            break
        try:
            vid = search_owned_video(info.get("query") or
                                     f"{info['full']} {info['opp_full']} highlights {day}",
                                     owners, info["opp_words"])
            source = label
        except Exception:
            pass
    if vid:
        return f"{YT}/watch?v={vid}&autoplay=1", source
    return highlights_search_url(info), "search"


# ---------------------------------------------------------------- ticker ----
class Ticker:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.league = self.cfg["league"]
        self.worker = Worker(root)
        self.logos = Logos(self.worker)
        self.games = []
        self.day = None          # None = the feed's "today"
        self.shown_date = ""
        self.week_label = ""
        self.offset = 0.0
        self.seq_w = 0
        self.paused = False
        self.scrolling = False
        self.detail_windows = {}
        self.standings_cache = {}     # league -> (timestamp, sections)
        self.f1 = None                # {"race": ..., "next": ...} for the F1 ticker
        self.f1_round = None          # None = latest race; else (season, round)
        self.f1_live = None           # live race state while a race/sprint is on
        self.f1_live_key = None
        self.f1_live_job = None
        self.f1_stream = None         # F1LiveTiming client (when signed in)
        self._espn_f1_data = None
        self._espn_f1_last = 0.0
        self._espn_f1_busy = False
        self._f1_live_sig = None
        self.refresh_job = None
        self.redraw_job = None
        self.fetch_token = 0
        self.status_msg = "Loading scores…"

        self.scale = root.winfo_fpixels("1i") / 96.0
        self.h = int(TICKER_HEIGHT * self.scale)
        self.logo_px = int(self.h * 0.56)

        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-topmost", bool(self.cfg["topmost"]))
        root.title(f"Sports Ticker v{APP_VERSION}")
        if sys.platform == "win32":   # app icon for the ticker and every window it opens
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            ico = os.path.join(base, "sports_ticker.ico")
            if os.path.exists(ico):
                try:
                    root.iconbitmap(default=ico)
                except tk.TclError:
                    pass

        self.f_abbr = tkfont.Font(family="Segoe UI", size=round(10 * K), weight="bold")
        self.f_score = tkfont.Font(family="Segoe UI", size=round(10 * K), weight="bold")
        self.f_dim = tkfont.Font(family="Segoe UI", size=round(10 * K))
        self.f_status = tkfont.Font(family="Segoe UI", size=round(9 * K), weight="bold")
        self.f_badge = tkfont.Font(family="Segoe UI Black", size=round(10 * K), weight="bold")

        # League badge / drop-down (left)
        self.badge = tk.Frame(root, bg=BADGE_BG, cursor="hand2")
        self.badge.pack(side="left", fill="y")
        self.badge_lbl = tk.Label(self.badge, text="", font=self.f_badge, bg=BADGE_BG,
                                  fg="#0b2a4a", padx=int(8 * K))
        self.badge_lbl.pack(side="left", fill="y")
        self.badge_arrow = tk.Label(self.badge, text="▾", font=self.f_dim, bg=BADGE_BG,
                                    fg="#33465c", padx=int(4 * K))
        self.badge_arrow.pack(side="left", fill="y")
        self.date_lbl = tk.Label(root, text="", font=self.f_status, bg=BG_PANEL,
                                 fg=FG_DIM, padx=8)
        self.date_lbl.pack(side="left", fill="y")

        # Close (X) button, drawn with lines so it renders on every system.
        cb = int(self.h * 1.1)
        self.close_btn = tk.Canvas(root, width=cb, height=self.h, bg=BG_PANEL,
                                   highlightthickness=0, cursor="hand2")
        self.close_btn.pack(side="right", fill="y")
        arm = self.h * 0.17
        lw = max(2, int(2 * self.scale))
        cx, cyy = cb / 2, self.h / 2
        for x1, y1, x2, y2 in ((cx - arm, cyy - arm, cx + arm, cyy + arm),
                               (cx - arm, cyy + arm, cx + arm, cyy - arm)):
            self.close_btn.create_line(x1, y1, x2, y2, width=lw, fill=FG,
                                       capstyle="round", tags="x")
        self.close_btn.bind("<Button-1>", lambda e: self.quit())
        self.close_btn.bind("<Enter>", lambda e: (self.close_btn.configure(bg="#e81123"),
                                                  self.close_btn.itemconfigure("x", fill="white")))
        self.close_btn.bind("<Leave>", lambda e: (self.close_btn.configure(bg=BG_PANEL),
                                                  self.close_btn.itemconfigure("x", fill=FG)))
        tk.Frame(root, width=1, bg=SEP).pack(side="right", fill="y")
        self.refresh_btn = tk.Label(root, text="↻", font=("Segoe UI Symbol", round(11 * K)),
                                    bg=BG_PANEL, fg=FG_DIM, cursor="hand2", padx=int(10 * K))
        self.refresh_btn.pack(side="right", fill="y")
        self.refresh_btn.bind("<Button-1>", lambda e: self.refresh())
        self.refresh_btn.bind("<Enter>", lambda e: self.refresh_btn.configure(fg=FG, bg=BG_HOVER))
        self.refresh_btn.bind("<Leave>", lambda e: self.refresh_btn.configure(fg=FG_DIM, bg=BG_PANEL))

        # Scrolling canvas
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0, height=self.h)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Enter>", lambda e: self._set_paused(True))
        self.canvas.bind("<Leave>", lambda e: self._set_paused(False))
        self.canvas.bind("<MouseWheel>", self._wheel)               # Windows
        self.canvas.bind("<Button-4>", lambda e: self._nudge(-60))  # X11
        self.canvas.bind("<Button-5>", lambda e: self._nudge(60))
        self.canvas.bind("<Configure>", lambda e: self.redraw())

        self.league_menu = self._build_league_menu()
        self.menu = self._build_menu()
        self._label_day_menu()
        for w in (root, self.canvas, self.date_lbl):
            w.bind("<Button-3>", self._popup)
        for w in (self.badge, self.badge_lbl, self.badge_arrow):
            w.bind("<Button-3>", self._popup)
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_end)
            w.bind("<Enter>", lambda e: self._badge_hover(True))
            w.bind("<Leave>", lambda e: self._badge_hover(False))
        self._drag = None

        self._update_badge()
        self.place_window()
        self.redraw()
        self.refresh()
        self._animate()
        self.root.after(1500, self._watch_screen)

    # ---- league selection ---------------------------------------------------
    def _build_league_menu(self):
        m = tk.Menu(self.root, tearoff=0, bg="white", fg="#111", activebackground="#dbe8f7",
                    activeforeground="#111", bd=0, font=("Segoe UI", 11))
        self.league_var = tk.StringVar(value=self.league)
        self.menu_imgs = {}
        for i, (key, lg) in enumerate(LEAGUES.items()):
            m.add_radiobutton(label=f"  {lg['name']}", value=key, variable=self.league_var,
                              command=lambda k=key: self.set_league(k))
            img = self.logos.get(lg["logo"], int(26 * self.scale),
                                 cb=lambda i=i, lg=lg: self._menu_logo(m, i, lg), dark=False)
            if img:
                self._menu_logo(m, i, lg)
        return m

    def _menu_logo(self, m, i, lg):
        img = self.logos.get(lg["logo"], int(26 * self.scale), dark=False)
        if img:
            self.menu_imgs[i] = img
            m.entryconfigure(i, image=img, compound="left")

    def _badge_hover(self, on):
        bg = "#dfe5ec" if on else BADGE_BG
        for w in (self.badge, self.badge_lbl, self.badge_arrow):
            w.configure(bg=bg)

    def _update_badge(self):
        lg = LEAGUES[self.league]
        img = self.logos.get(lg["logo"], int(self.h * 0.8), cb=self._update_badge, dark=False)
        if img:
            self.badge_lbl.configure(image=img, text="")
            self.badge_lbl.image = img
        else:
            self.badge_lbl.configure(image="", text=lg["name"])

    def _open_league_menu(self):
        x = self.badge.winfo_rootx()
        y = self.badge.winfo_rooty() + self.badge.winfo_height()
        if y + 200 > self.root.winfo_screenheight():    # docked at bottom: open upward
            y = self.badge.winfo_rooty() - 6 * int(34 * self.scale)
        try:
            self.league_menu.tk_popup(x, y)
        finally:
            self.league_menu.grab_release()

    def set_league(self, key):
        if key == self.league:
            return
        self.league = key
        self.cfg["league"] = key
        self.league_var.set(key)
        save_config(self.cfg)
        self._update_badge()
        self.day = None
        self.games = []
        self.f1 = None
        self.f1_round = None
        self._f1_live_end()
        self._label_day_menu()
        self.week_label = ""
        self.status_msg = f"Loading {LEAGUES[key]['name']} " + \
            ("results…" if key == "f1" else "scores…")
        self.offset = 0
        self.date_lbl.configure(text="")
        self.redraw()
        self.refresh()

    # ---- reserved screen space (Windows "AppBar", like the taskbar) ---------
    def _appbar_api(self):
        if sys.platform != "win32":
            return None
        if getattr(self, "_ab", None) is None:
            try:
                import ctypes
                from ctypes import wintypes

                class APPBARDATA(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                                ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]
                shell32, user32 = ctypes.windll.shell32, ctypes.windll.user32
                shell32.SHAppBarMessage.argtypes = [wintypes.DWORD, ctypes.POINTER(APPBARDATA)]
                shell32.SHAppBarMessage.restype = ctypes.c_size_t
                user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
                user32.GetAncestor.restype = wintypes.HWND
                self.root.update_idletasks()
                hwnd = user32.GetAncestor(self.root.winfo_id(), 2) or self.root.winfo_id()
                abd = APPBARDATA()
                abd.cbSize = ctypes.sizeof(APPBARDATA)
                abd.hWnd = hwnd
                abd.uCallbackMessage = user32.RegisterWindowMessageW("SportsTickerAppBar")
                self._ab = {"ct": ctypes, "msg": shell32.SHAppBarMessage, "abd": abd,
                            "user32": user32, "hwnd": hwnd, "registered": False}
            except Exception:
                self._ab = False
        return self._ab or None

    def _appbar_register(self, edge_name):
        ab = self._appbar_api()
        if not ab:
            return None
        ct, msg, abd, user32 = ab["ct"], ab["msg"], ab["abd"], ab["user32"]
        try:
            if not ab["registered"]:
                if not msg(0, ct.byref(abd)):          # ABM_NEW
                    return None
                ab["registered"] = True
            edge = 1 if edge_name == "top" else 3      # ABE_TOP / ABE_BOTTOM
            abd.uEdge = edge
            sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
            abd.rc.left, abd.rc.right = 0, sw
            if edge == 1:
                abd.rc.top, abd.rc.bottom = 0, self.h
            else:
                abd.rc.top, abd.rc.bottom = sh - self.h, sh
            msg(2, ct.byref(abd))                      # ABM_QUERYPOS (avoids the taskbar)
            if edge == 1:
                abd.rc.bottom = abd.rc.top + self.h
            else:
                abd.rc.top = abd.rc.bottom - self.h
            msg(3, ct.byref(abd))                      # ABM_SETPOS
            return abd.rc.left, abd.rc.top, abd.rc.right - abd.rc.left
        except Exception:
            return None

    def appbar_remove(self):
        ab = getattr(self, "_ab", None)
        if ab and ab["registered"]:
            try:
                ab["msg"](1, ab["ct"].byref(ab["abd"]))  # ABM_REMOVE
            except Exception:
                pass
            ab["registered"] = False

    def _watch_screen(self):
        """Re-dock after resolution changes; step aside for full-screen apps."""
        try:
            size = (self.root.winfo_screenwidth(), self.root.winfo_screenheight())
            if size != getattr(self, "_last_screen", size):
                self.place_window()
            self._last_screen = size
            ab = self._appbar_api()
            if ab and self.cfg["topmost"]:
                fs = self._foreground_is_fullscreen(ab)
                if fs != getattr(self, "_fs", False):
                    self._fs = fs
                    self.root.attributes("-topmost", not fs)
                    if fs:
                        self.root.lower()
        except Exception:
            pass
        self.root.after(1000, self._watch_screen)

    def _foreground_is_fullscreen(self, ab):
        ct, user32 = ab["ct"], ab["user32"]
        from ctypes import wintypes
        fg = user32.GetForegroundWindow()
        if not fg or fg == ab["hwnd"]:
            return False
        buf = ct.create_unicode_buffer(64)
        user32.GetClassNameW(fg, buf, 64)
        if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
            return False
        r = wintypes.RECT()
        user32.GetWindowRect(fg, ct.byref(r))
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        return r.left <= 0 and r.top <= 0 and r.right >= sw and r.bottom >= sh

    # ---- window placement -------------------------------------------------
    def work_area(self):
        if sys.platform == "win32":
            try:
                import ctypes
                from ctypes import wintypes
                r = wintypes.RECT()
                ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(r), 0)
                return r.left, r.top, r.right, r.bottom
            except Exception:
                pass
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def place_window(self):
        pos = self.cfg.get("position", "top")
        if self.cfg.get("reserve", True) and pos in ("top", "bottom"):
            got = self._appbar_register(pos)
            if got:
                left, y, w = got
                self.root.geometry(f"{w}x{self.h}+{left}+{y}")
                return
        else:
            self.appbar_remove()
        left, top, right, bottom = self.work_area()
        w = right - left
        if pos == "custom" and self.cfg.get("y") is not None:
            y = max(top, min(int(self.cfg["y"]), bottom - self.h))
        elif pos == "bottom":
            y = bottom - self.h
        else:
            y = top
        self.root.geometry(f"{w}x{self.h}+{left}+{y}")

    def set_position(self, pos):
        if pos == "custom" and self.cfg.get("reserve", True):
            self.cfg["reserve"] = False
            self.reserve_var.set(False)
        self.cfg["position"] = pos
        save_config(self.cfg)
        self.place_window()

    def _drag_start(self, e):
        self._drag = (e.y_root, self.root.winfo_y(), False)

    def _drag_move(self, e):
        if not self._drag:
            return
        y0, wy, _ = self._drag
        dy = e.y_root - y0
        if abs(dy) > 4:
            self._drag = (y0, wy, True)
            self.root.geometry(f"+{self.root.winfo_x()}+{wy + dy}")

    def _drag_end(self, e):
        if self._drag and self._drag[2]:
            if self.cfg.get("reserve", True):
                mid = self.root.winfo_y() + self.h / 2
                pos = "top" if mid < self.root.winfo_screenheight() / 2 else "bottom"
            else:
                pos = "custom"
                self.cfg["y"] = self.root.winfo_y()
            self.cfg["position"] = pos
            self.pos_var.set(pos)
            save_config(self.cfg)
            self.place_window()
        else:
            self._open_league_menu()
        self._drag = None

    # ---- settings menu ------------------------------------------------------
    def _build_menu(self):
        def sub():
            return tk.Menu(m, tearoff=0, bg=BG_PANEL, fg=FG, activebackground=ACCENT)
        m = tk.Menu(self.root, tearoff=0, bg=BG_PANEL, fg=FG, activebackground=ACCENT,
                    activeforeground="white", bd=0)
        lg = sub()
        for key, info in LEAGUES.items():
            lg.add_radiobutton(label=info["name"], value=key, variable=self.league_var,
                               command=lambda k=key: self.set_league(k))
        m.add_cascade(label="League", menu=lg)
        m.add_command(label="Refresh now", command=self.refresh)
        m.add_separator()
        m.add_command(label="◀  Previous day", command=lambda: self.shift_day(-1))
        m.add_command(label="Today", command=lambda: self.shift_day(None))
        m.add_command(label="Next day  ▶", command=lambda: self.shift_day(1))
        m.add_separator()

        self.scroll_var = tk.BooleanVar(value=self.cfg["scroll"])
        m.add_checkbutton(label="Scroll games", variable=self.scroll_var,
                          command=self._toggle_scroll)
        speed = sub()
        self.speed_var = tk.IntVar(value=self.cfg["speed"])
        for label, v in (("Slow", 1), ("Medium", 2), ("Fast", 3)):
            speed.add_radiobutton(label=label, value=v, variable=self.speed_var,
                                  command=self._set_speed)
        m.add_cascade(label="Scroll speed", menu=speed)
        direc = sub()
        self.dir_var = tk.StringVar(value=self.cfg.get("direction", "ltr"))
        for label, v in (("Left to right  →", "ltr"), ("Right to left  ←", "rtl")):
            direc.add_radiobutton(label=label, value=v, variable=self.dir_var,
                                  command=self._set_direction)
        m.add_cascade(label="Scroll direction", menu=direc)

        pos = sub()
        self.pos_var = tk.StringVar(value=self.cfg["position"])
        pos.add_radiobutton(label="Top of screen", value="top", variable=self.pos_var,
                            command=lambda: self.set_position("top"))
        pos.add_radiobutton(label="Bottom (above taskbar)", value="bottom",
                            variable=self.pos_var, command=lambda: self.set_position("bottom"))
        pos.add_radiobutton(label="Where I dragged it (floats over windows)", value="custom",
                            variable=self.pos_var, command=lambda: self.set_position("custom"))
        m.add_cascade(label="Position", menu=pos)
        self.reserve_var = tk.BooleanVar(value=self.cfg.get("reserve", True))
        m.add_checkbutton(label="Keep windows from going under the ticker",
                          variable=self.reserve_var, command=self._toggle_reserve)
        self.top_var = tk.BooleanVar(value=self.cfg["topmost"])
        m.add_checkbutton(label="Always on top", variable=self.top_var,
                          command=self._toggle_topmost)
        m.add_command(label="F1 live timing sign-in…", command=self.f1_signin_dialog)
        m.add_separator()
        m.add_command(label="Uninstall Sports Ticker…", command=self.uninstall)
        m.add_command(label="Exit", command=self.quit)
        m.add_separator()
        m.add_command(label="What's new…", command=self.show_changelog)
        m.add_command(label=f"Sports Ticker v{APP_VERSION}", state="disabled")
        return m

    # ---- uninstall -------------------------------------------------------------
    APP_FILES = ("sports_ticker.pyw", "sports_ticker.ico", "Start Sports Ticker.bat",
                 "Build EXE.bat", "README.md", "CHANGELOG.md", ".gitignore",
                 "SportsTicker_Setup.exe", r"installer\SportsTicker.nsi",
                 r"installer\welcome.bmp", r"installer\header.bmp")

    def _app_dir(self):
        if getattr(sys, "frozen", False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _find_uninstaller(self):
        cand = os.path.join(self._app_dir(), "Uninstall.exe")
        if os.path.exists(cand):
            return cand
        if sys.platform == "win32":
            try:
                import winreg
                key = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\SportsTicker"
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                    path = winreg.QueryValueEx(k, "UninstallString")[0].strip('"')
                    if os.path.exists(path):
                        return path
            except OSError:
                pass
        return None

    def uninstall(self):
        uninst = self._find_uninstaller()
        if uninst:
            if not messagebox.askyesno(
                    "Uninstall Sports Ticker",
                    "Remove Sports Ticker from this PC?\n\nThe ticker will close and the "
                    "uninstaller will open. It removes the app and its shortcuts, and asks "
                    "whether to keep your settings."):
                return
            subprocess.Popen([uninst], close_fds=True)
            self.quit()
            return
        if sys.platform != "win32":
            messagebox.showinfo("Uninstall Sports Ticker",
                                "To remove Sports Ticker, close it and delete its folder:\n"
                                + self._app_dir())
            return
        folder = self._app_dir()
        if not messagebox.askyesno(
                "Uninstall Sports Ticker",
                "Sports Ticker is running from a folder rather than from the installer.\n\n"
                "Remove it now? The ticker will close, and these are deleted:\n"
                "•  its settings and downloaded logos\n"
                "•  its startup and desktop shortcuts, if there are any\n"
                f"•  the Sports Ticker files in {folder}\n\n"
                "Anything else you've put in that folder is left alone."):
            return
        try:
            import shutil
            shutil.rmtree(CONFIG_DIR, ignore_errors=True)
            for lnk in (os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu"
                                     r"\Programs\Startup\Sports Ticker.lnk"),
                        os.path.join(os.path.expanduser("~"), "Desktop", "Sports Ticker.lnk")):
                if os.path.exists(lnk):
                    os.remove(lnk)
        except OSError:
            pass
        # Delete the app's own files once it has exited, then the folders if empty.
        files = " ".join(f'"{os.path.join(folder, f)}"' for f in self.APP_FILES)
        cmd = (f'ping -n 3 127.0.0.1 >nul & del /f /q {files} 2>nul & '
               f'rmdir /s /q "{os.path.join(folder, "__pycache__")}" 2>nul & '
               f'rmdir "{os.path.join(folder, "installer")}" 2>nul & rmdir "{folder}" 2>nul')
        subprocess.Popen(["cmd", "/c", cmd], creationflags=0x08000000, close_fds=True)
        self.quit()

    def show_changelog(self):
        win = getattr(self, "_changelog_win", None)
        if win is not None and win.winfo_exists():
            win.deiconify()
            win.lift()
            return
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        try:
            with open(os.path.join(base, "CHANGELOG.md"), "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            text = f"Sports Ticker v{APP_VERSION}\n\n(CHANGELOG.md wasn't found next to the app.)"
        win = tk.Toplevel(self.root, bg=BG)
        self._changelog_win = win
        win.title(f"What's new — Sports Ticker v{APP_VERSION}")
        w, h = int(640 * self.scale), int(620 * self.scale)
        win.geometry(f"{w}x{h}+{(self.root.winfo_screenwidth() - w) // 2}+"
                     f"{(self.root.winfo_screenheight() - h) // 2}")
        win.attributes("-topmost", True)
        win.after(400, lambda: win.winfo_exists() and win.attributes("-topmost", False))
        win.bind("<Escape>", lambda e: win.destroy())
        box = tk.Text(win, bg=BG, fg=FG, insertbackground=FG, relief="flat", wrap="word",
                      font=("Segoe UI", 10), padx=18, pady=14, spacing1=2, spacing3=2)
        sb = ttk.Scrollbar(win, orient="vertical", command=box.yview)
        box.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        box.tag_configure("h1", font=("Segoe UI", 16, "bold"), foreground=FG, spacing3=6)
        box.tag_configure("h2", font=("Segoe UI", 12, "bold"), foreground=ACCENT, spacing1=12)
        box.tag_configure("h3", font=("Segoe UI", 10, "bold"), foreground="#ffd166", spacing1=4)
        box.tag_configure("dim", foreground=FG_DIM)
        for line in text.splitlines():
            clean = line.replace("**", "").replace("`", "")
            if line.startswith("### "):
                box.insert("end", clean[4:] + "\n", "h3")
            elif line.startswith("## "):
                box.insert("end", clean[3:] + "\n", "h2")
            elif line.startswith("# "):
                box.insert("end", clean[2:] + "\n", "h1")
            elif line.startswith("- "):
                box.insert("end", "  •  " + clean[2:] + "\n")
            elif line.startswith("  ") and clean.strip():
                box.insert("end", "      " + clean.strip() + "\n")
            else:
                box.insert("end", clean + "\n", "dim")
        box.configure(state="disabled")

    def _popup(self, e):
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def _toggle_scroll(self):
        self.cfg["scroll"] = self.scroll_var.get()
        save_config(self.cfg)
        self.offset = 0
        self.redraw()

    def _set_speed(self):
        self.cfg["speed"] = self.speed_var.get()
        save_config(self.cfg)

    def _toggle_reserve(self):
        self.cfg["reserve"] = self.reserve_var.get()
        if self.cfg["reserve"] and self.cfg.get("position") == "custom":
            self.cfg["position"] = "top"
            self.pos_var.set("top")
        save_config(self.cfg)
        self.place_window()

    def _set_direction(self):
        self.cfg["direction"] = self.dir_var.get()
        save_config(self.cfg)

    def _toggle_topmost(self):
        self.cfg["topmost"] = self.top_var.get()
        self.root.attributes("-topmost", self.cfg["topmost"])
        save_config(self.cfg)

    def _label_day_menu(self):
        """For F1 the day buttons step through races instead of dates."""
        f1 = self.league == "f1"
        try:
            self.menu.entryconfigure(3, label="◀  Previous race" if f1 else "◀  Previous day")
            self.menu.entryconfigure(4, label="Latest race" if f1 else "Today")
            self.menu.entryconfigure(5, label="Next race  ▶" if f1 else "Next day  ▶")
        except (tk.TclError, AttributeError):
            pass

    def shift_day(self, delta):
        if self.league == "f1":
            race = (self.f1 or {}).get("race")
            if delta is None or not race:
                self.f1_round = None
            else:
                season, rnd = int(race["season"]), int(race["round"]) + delta
                self.f1_round = (season, max(1, rnd))
            self.f1 = None
            self.status_msg = "Loading F1 results…"
            self.offset = 0
            self.redraw()
            self.refresh()
            return
        if delta is None:
            self.day = None
        else:
            self.day = self._target_day() + timedelta(days=delta)
            if self.day == date.today():
                self.day = None      # back on today: follow the calendar again
        self.games = []
        self.status_msg = "Loading scores…"
        self.offset = 0
        self.redraw()
        self.refresh()

    def quit(self):
        save_config(self.cfg)
        self._f1_live_end()
        self.appbar_remove()
        self.root.destroy()

    # ---- data refresh ------------------------------------------------------
    def _target_day(self):
        """The date being shown: the chosen day, or today on this PC's calendar."""
        return self.day or date.today()

    def _scores_url(self, league, day):
        lg = LEAGUES[league]
        if lg["provider"] == "nhl":
            return f"{NHL_API}/score/{day.isoformat()}"
        return f"{ESPN_API}/{lg['espn']}/scoreboard?dates={day.strftime('%Y%m%d')}"

    def _normalize(self, data, league):
        if LEAGUES[league]["provider"] == "nhl":
            return [nhl_normalize(g) for g in data.get("games", []) or []]
        return [espn_normalize(ev, league) for ev in data.get("events", []) or []]

    def refresh(self):
        if self.refresh_job:
            self.root.after_cancel(self.refresh_job)
            self.refresh_job = None
        self.fetch_token += 1
        if self.league == "f1":
            self._refresh_f1(self.fetch_token)
            return
        token, league, day = self.fetch_token, self.league, self._target_day()
        url = self._scores_url(league, day)
        # Just after midnight, keep showing last night's games that are still going.
        yurl = self._scores_url(league, day - timedelta(days=1)) \
            if self.day is None and datetime.now().hour < 4 else None

        def work():
            data = fetch_json(url)
            yday = None
            if yurl:
                try:
                    yday = fetch_json(yurl)
                except Exception:
                    pass
            return data, yday
        self.worker.run(work,
                        lambda r: token == self.fetch_token and self._on_scores(
                            r[0], league, day, r[1]),
                        lambda e: token == self.fetch_token and self._on_error(e))

    def _on_scores(self, data, league, day, yday=None):
        self.games = self._normalize(data, league)
        if yday:
            have = {g["id"] for g in self.games}
            self.games += [g for g in self._normalize(yday, league)
                           if g["kind"] == "live" and g["id"] not in have]
        self.shown_date = day.isoformat()
        self.week_label = ""
        self.empty_next = ""
        if self.games:
            self.status_msg = ""
        else:
            name = LEAGUES[league]["name"]
            when = "today" if self.day is None else "on " + day.strftime("%a %b ") + str(day.day)
            self.status_msg = f"No {name} games {when}"
            nxt = next_game_day(data, league, self.shown_date)
            if nxt:
                self.empty_next = "Next games: " + nxt.strftime("%a %b ") + str(nxt.day)
            elif LEAGUES[league]["provider"] == "espn":
                self._look_ahead(league, day)
        self._update_date_label()
        self.redraw()
        for key, win in list(self.detail_windows.items()):
            g = next((x for x in self.games if (x["league"], x["id"]) == key), None)
            if g and win.alive:
                win.update_header(g)
        any_live = any(g["kind"] == "live" for g in self.games)
        wait = 20000 if any_live else 120000
        if self.day is None:   # roll over to the new day right after midnight
            now = datetime.now()
            midnight = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
            wait = min(wait, int((midnight - now).total_seconds() * 1000) + 5000)
        self.refresh_job = self.root.after(wait, self.refresh)

    # ---- F1 -----------------------------------------------------------------
    def _refresh_f1(self, token):
        sel = self.f1_round

        def work():
            if sel is None:
                last = fetch_json(f"{JOLPICA}/current/last/results.json")
                try:
                    nxt = fetch_json(f"{JOLPICA}/current/next.json")
                except Exception:
                    nxt = {}
            else:
                last = fetch_json(f"{JOLPICA}/{sel[0]}/{sel[1]}/results.json")
                nxt = {}
                if not ((last.get("MRData") or {}).get("RaceTable") or {}).get("Races"):
                    # Not raced yet: show that round's schedule instead.
                    nxt = fetch_json(f"{JOLPICA}/{sel[0]}/{sel[1]}.json")
            return last, nxt
        self.worker.run(work,
                        lambda r: token == self.fetch_token and self._on_f1(*r),
                        lambda e: token == self.fetch_token and self._on_error(e))

    def _on_f1(self, last, nxt):
        races = ((last.get("MRData") or {}).get("RaceTable") or {}).get("Races") or []
        nraces = ((nxt.get("MRData") or {}).get("RaceTable") or {}).get("Races") or []
        race = races[0] if races else None
        upcoming = nraces[0] if nraces else None
        self.games = []
        self.f1 = {"race": race, "next": upcoming}
        self.empty_next = ""
        if race or upcoming:
            self.status_msg = ""
        else:
            self.status_msg = "No F1 race results yet" + \
                (f" for round {self.f1_round[1]}" if self.f1_round else " this season")
        shown = race or upcoming
        if shown:
            self.date_lbl.configure(text=f"{shown.get('season', '')} · Round {shown.get('round', '')}")
        else:
            self.date_lbl.configure(text="F1")
        which = self._f1_live_window(upcoming) if (upcoming and self.f1_round is None) else None
        if which:
            self._f1_live_begin(upcoming, which)
        else:
            self._f1_live_end()
        self.redraw()
        # Results land within an hour or so of the chequered flag; check every 5 min.
        self.refresh_job = self.root.after(300000, self.refresh)

    # ---- F1 live race --------------------------------------------------------
    @staticmethod
    def _f1_live_window(race):
        """'Race' or 'Sprint' if one is on right now (by the schedule), else None."""
        if os.environ.get("SPORTS_TICKER_FORCE_F1_LIVE"):
            return os.environ["SPORTS_TICKER_FORCE_F1_LIVE"]
        now = datetime.now(timezone.utc)
        for key, hours in (("Sprint", 1.5), (None, 3.0)):
            st = f1_start(race.get(key) if key else race)
            if st and st - timedelta(minutes=10) <= now <= st + timedelta(hours=hours):
                return "Sprint" if key else "Race"
        return None

    def _f1_live_begin(self, race, which):
        key = (race.get("season"), race.get("round"), which)
        if self.f1_live_key == key:
            return
        self._f1_live_end()
        self.f1_live_key = key
        self.f1_live = {"race": race, "which": which, "rows": [], "source": "", "lap": "",
                        "track": "", "note": "Waiting for live timing…"}
        # F1's live timing serves positions and gaps without signing in; an F1
        # account sign-in, if saved, is used too and dropped if it's rejected.
        self.f1_stream = F1LiveTiming(self.cfg.get("f1_token") or "").start()
        self._f1_live_tick()

    def _f1_live_end(self):
        if self.f1_live_job:
            try:
                self.root.after_cancel(self.f1_live_job)
            except tk.TclError:
                pass
        self.f1_live_job = None
        if self.f1_stream:
            self.f1_stream.stop()
        self.f1_stream = None
        self.f1_live = self.f1_live_key = self._espn_f1_data = self._f1_live_sig = None

    def _f1_live_tick(self):
        self.f1_live_job = None
        if not self.f1_live:
            return
        data, note = None, ""
        if self.f1_stream:
            snap = self.f1_stream.snapshot()
            if (snap.get("TimingData") or {}).get("Lines"):
                data = f1_rows_from_timing(snap)
                data["source"] = "F1 live timing"
            else:
                note = self.f1_stream.status
        if data is None:
            if time.time() - self._espn_f1_last > 9 and not self._espn_f1_busy:
                self._espn_f1_busy = True
                self._espn_f1_last = time.time()
                self.worker.run(lambda: fetch_json(f"{ESPN_API}/racing/f1/scoreboard"),
                                self._on_espn_f1,
                                lambda e: setattr(self, "_espn_f1_busy", False))
            if self._espn_f1_data:
                data = dict(self._espn_f1_data)
                data["rows"] = [dict(r) for r in self._espn_f1_data["rows"]]
                data["source"] = "ESPN (no gaps: waiting for F1 live timing)"
        if data and data.get("rows"):
            teams = self._f1_team_map()
            for r in data["rows"]:
                if r.get("color") in (None, "", FG_DIM):
                    hit = teams.get(r.get("code", "").upper()) or teams.get(
                        norm((r.get("name") or "").split(" ")[-1])) or teams.get(str(r.get("num")))
                    if hit:
                        r["color"], r["team"] = hit[0], r.get("team") or hit[1]
            fill_intervals(data["rows"])
            data["note"] = ""
            self.f1_live.update(data)
        else:
            self.f1_live["note"] = note or "Waiting for live timing…"
        sig = (tuple((r["pos"], r["code"], r.get("interval"), r.get("status"))
                     for r in self.f1_live["rows"]),
               self.f1_live.get("lap"), self.f1_live.get("track"), self.f1_live.get("note"))
        if sig != self._f1_live_sig:
            self._f1_live_sig = sig
            self.redraw()
        # Gaps refresh every 10 s; check sooner until the first live data arrives.
        wait = 10000 if self.f1_live["rows"] and self.f1_live.get("source", "").startswith("F1") \
            else 2500
        self.f1_live_job = self.root.after(wait, self._f1_live_tick)

    def _f1_team_map(self):
        """Driver -> (team colour, team name) from the latest race results, for
        live feeds that don't say which team each driver drives for."""
        race = (self.f1 or {}).get("race") or {}
        key = (race.get("season"), race.get("round"))
        if getattr(self, "_team_map_key", None) == key:
            return self._team_map
        m = {}
        for r in race.get("Results") or []:
            d = r.get("Driver") or {}
            val = (f1_team_color(r), (r.get("Constructor") or {}).get("name", ""))
            for k in (str(d.get("code", "")).upper(), norm(d.get("familyName", "")),
                      str(r.get("number", ""))):
                if k:
                    m[k] = val
        self._team_map_key, self._team_map = key, m
        return m

    def _on_espn_f1(self, data):
        self._espn_f1_busy = False
        parsed = espn_f1_live(data)
        if parsed and parsed.get("rows"):
            self._espn_f1_data = parsed

    def f1_signin_dialog(self):
        win = getattr(self, "_signin_win", None)
        if win is not None and win.winfo_exists():
            win.lift()
            return
        style_once(self.root)
        win = tk.Toplevel(self.root, bg=BG)
        self._signin_win = win
        win.title("F1 live timing sign-in")
        w, h = int(620 * self.scale), int(560 * self.scale)
        win.geometry(f"{w}x{h}+{(self.root.winfo_screenwidth() - w) // 2}+"
                     f"{(self.root.winfo_screenheight() - h) // 2}")
        win.attributes("-topmost", True)
        win.after(400, lambda: win.winfo_exists() and win.attributes("-topmost", False))
        pad = {"padx": 18, "anchor": "w"}
        tk.Label(win, text="F1 live timing sign-in", font=("Segoe UI", 15, "bold"), bg=BG,
                 fg=FG).pack(pady=(16, 6), **pad)
        tk.Label(win, justify="left", wraplength=w - 40, bg=BG, fg=FG, font=("Segoe UI", 10),
                 text="You don't need to sign in: during races the ticker connects to F1's "
                      "official live timing by itself, with the gap between every driver. "
                      "Signing in is a backup in case F1 starts requiring an account. A free "
                      "formula1.com account works; if F1 ever rejects it, the ticker simply "
                      "carries on without it.\n\n"
                      "1.  In your web browser, sign in at formula1.com with your F1 account.\n"
                      "2.  Press F12 to open the developer tools, then go to Application "
                      "(Chrome or Edge) or Storage (Firefox) > Cookies > "
                      "https://www.formula1.com.\n"
                      "3.  Click the cookie named login-session and copy its Value.\n"
                      "4.  Paste it below and click Save.\n\n"
                      "The sign-in lasts a few days; when it runs out, the ticker tells you, "
                      "and you repeat these steps. It's stored only on this PC, in the "
                      "ticker's settings file.").pack(**pad)
        box = tk.Text(win, height=5, bg="#0b1017", fg=FG, insertbackground=FG, relief="flat",
                      font=("Consolas", 9), wrap="char")
        box.pack(fill="x", padx=18, pady=(12, 6))
        status = tk.Label(win, text="", bg=BG, fg=FG_DIM, font=("Segoe UI", 9), justify="left",
                          wraplength=w - 40)
        status.pack(**pad)

        def show():
            tok = self.cfg.get("f1_token")
            if not tok:
                status.configure(text="Not signed in (not needed): live races use F1's free "
                                      "live timing.", fg=FG_DIM)
                return
            exp = jwt_expiry(tok)
            if exp and exp < datetime.now(timezone.utc):
                status.configure(text="Your F1 sign-in has expired. Paste a fresh "
                                      "login-session value to renew it.", fg=LIVE)
            elif exp:
                status.configure(text="Signed in. Valid until " +
                                      exp.astimezone().strftime("%a %b %d, %I:%M %p"), fg=GOOD)
            else:
                status.configure(text="Signed in.", fg=GOOD)

        def restart_stream():
            if self.f1_live:
                race, which = self.f1_live["race"], self.f1_live["which"]
                self._f1_live_end()
                self._f1_live_begin(race, which)

        def save():
            tok = extract_f1_token(box.get("1.0", "end"))
            if not tok:
                status.configure(text="That doesn't look like the login-session cookie value. "
                                      "Copy the whole Value and try again.", fg=LIVE)
                return
            self.cfg["f1_token"] = tok
            save_config(self.cfg)
            box.delete("1.0", "end")
            show()
            restart_stream()

        def remove():
            self.cfg["f1_token"] = ""
            save_config(self.cfg)
            show()
            restart_stream()

        btns = tk.Frame(win, bg=BG)
        btns.pack(fill="x", padx=18, pady=12)
        for label, cmd, bg in (("Save", save, ACCENT), ("Sign out", remove, "#3a4656"),
                               ("Close", win.destroy, "#3a4656")):
            b = tk.Label(btns, text=label, bg=bg, fg="white", font=("Segoe UI", 10, "bold"),
                         padx=14, pady=5, cursor="hand2")
            b.pack(side="left", padx=(0, 8))
            b.bind("<Button-1>", lambda e, c=cmd: c())
        win.bind("<Escape>", lambda e: win.destroy())
        show()

    def _draw_f1_live_seq(self, x, cy):
        c = self.canvas
        u = self.scale * K
        live = self.f1_live
        race = live["race"]

        def chip(x0, draw, tag):
            x = draw(x0 + 14 * u)
            bg = c.create_rectangle(x0, 0, x + 14 * u, self.h, fill=BG, outline="",
                                    tags=("content", tag, "bg"))
            c.tag_lower(bg)
            x += 14 * u
            c.create_line(x, 10 * u, x, self.h - 10 * u, fill=SEP, tags=("content",))
            c.tag_bind(tag, "<Button-1>", lambda e: self.open_f1(race))
            c.tag_bind(tag, "<Enter>", lambda e, t=tag: self._hover(t, True))
            c.tag_bind(tag, "<Leave>", lambda e, t=tag: self._hover(t, False))
            return x + 1

        tag = f"f1L{x:.0f}"

        def head(x):
            r = 4 * u
            c.create_oval(x, cy - r, x + 2 * r, cy + r, fill=LIVE, outline="",
                          tags=("content", tag))
            x += 2 * r + 6 * u
            i = c.create_text(x, cy, text="LIVE", anchor="w", font=self.f_status, fill=LIVE,
                              tags=("content", tag))
            x = c.bbox(i)[2] + 10 * u
            name = f1_short(race.get("raceName")).upper()
            if live["which"] == "Sprint":
                name += " SPRINT"
            i = c.create_text(x, cy, text=name, anchor="w", font=self.f_abbr, fill=FG,
                              tags=("content", tag))
            x = c.bbox(i)[2] + 10 * u
            if live.get("lap"):
                i = c.create_text(x, cy, text=f"LAP {live['lap']}", anchor="w",
                                  font=self.f_status, fill=FG_DIM, tags=("content", tag))
                x = c.bbox(i)[2] + 10 * u
            if live.get("track"):
                i = c.create_text(x, cy, text=live["track"], anchor="w", font=self.f_status,
                                  fill="#ffd166", tags=("content", tag))
                x = c.bbox(i)[2] + 10 * u
            if not live["rows"]:
                i = c.create_text(x, cy, text=live.get("note") or "", anchor="w",
                                  font=self.f_dim, fill=FG_DIM, tags=("content", tag))
                x = c.bbox(i)[2]
            return x
        x = chip(x, head, tag)
        for n, r in enumerate(live["rows"]):
            tag = f"f1l{n}_{x:.0f}"

            def drv(x, r=r, tag=tag):
                pos = r["pos"]
                i = c.create_text(x, cy, text=str(pos), anchor="w", font=self.f_score,
                                  fill=PODIUM.get(pos, FG_DIM), tags=("content", tag))
                x = c.bbox(i)[2] + 7 * u
                c.create_rectangle(x, cy - 8 * u, x + 4 * u, cy + 8 * u, fill=r["color"],
                                   outline="", tags=("content", tag))
                x += 9 * u
                i = c.create_text(x, cy, text=r["code"], anchor="w", font=self.f_abbr, fill=FG,
                                  tags=("content", tag))
                x = c.bbox(i)[2] + 7 * u
                split = r.get("interval") or ""
                if split:
                    i = c.create_text(x, cy, text=split, anchor="w", font=self.f_dim,
                                      fill=ACCENT if split == "LEADER" else FG_DIM,
                                      tags=("content", tag))
                    x = c.bbox(i)[2]
                if r.get("status"):
                    i = c.create_text(x + 8 * u, cy, text=r["status"], anchor="w",
                                      font=self.f_status,
                                      fill="#ffd166" if r["status"] == "PIT" else LIVE,
                                      tags=("content", tag))
                    x = c.bbox(i)[2]
                return x
            x = chip(x, drv, tag)
        return x

    def _draw_f1_seq(self, x, cy):
        if self.f1_live:
            return self._draw_f1_live_seq(x, cy)
        c = self.canvas
        u = self.scale * K
        race, nxt = self.f1.get("race"), self.f1.get("next")

        def chip(x0, draw, tag, target):
            x = draw(x0 + 14 * u)
            bg = c.create_rectangle(x0, 0, x + 14 * u, self.h, fill=BG, outline="",
                                    tags=("content", tag, "bg"))
            c.tag_lower(bg)
            x += 14 * u
            c.create_line(x, 10 * u, x, self.h - 10 * u, fill=SEP, tags=("content",))
            c.tag_bind(tag, "<Button-1>", lambda e, r=target: self.open_f1(r))
            c.tag_bind(tag, "<Enter>", lambda e, t=tag: self._hover(t, True))
            c.tag_bind(tag, "<Leave>", lambda e, t=tag: self._hover(t, False))
            return x + 1

        def flag(x, tag):        # small chequered flag
            sq = max(3, int(4 * u))
            top = cy - sq
            for row in range(2):
                for col in range(4):
                    c.create_rectangle(x + col * sq, top + row * sq, x + (col + 1) * sq,
                                       top + (row + 1) * sq, outline="",
                                       fill="white" if (row + col) % 2 == 0 else "#222",
                                       tags=("content", tag))
            return x + 4 * sq + 8 * u

        if race:
            tag = f"f1r{x:.0f}"

            def head(x):
                x = flag(x, tag)
                i = c.create_text(x, cy, text=f1_short(race.get("raceName")).upper(), anchor="w",
                                  font=self.f_abbr, fill=FG, tags=("content", tag))
                x = c.bbox(i)[2] + 10 * u
                st = f1_start(race)
                when = local_day(st.isoformat()) if st else race.get("date", "")
                i = c.create_text(x, cy, text=f"{when} · FINAL", anchor="w", font=self.f_status,
                                  fill=FG_DIM, tags=("content", tag))
                return c.bbox(i)[2]
            x = chip(x, head, tag, race)
            results = race.get("Results") or []
            splits = f1_splits(results)
            for n, r in enumerate(results):
                tag = f"f1d{n}_{x:.0f}"

                def drv(x, r=r, tag=tag, split=splits[n]):
                    pos = int(r.get("position") or 0)
                    i = c.create_text(x, cy, text=str(pos), anchor="w", font=self.f_score,
                                      fill=PODIUM.get(pos, FG_DIM), tags=("content", tag))
                    x = c.bbox(i)[2] + 7 * u
                    c.create_rectangle(x, cy - 8 * u, x + 4 * u, cy + 8 * u,
                                       fill=f1_team_color(r), outline="", tags=("content", tag))
                    x += 9 * u
                    i = c.create_text(x, cy, text=f1_driver(r), anchor="w", font=self.f_abbr,
                                      fill=FG, tags=("content", tag))
                    x = c.bbox(i)[2] + 7 * u
                    res = split
                    i = c.create_text(x, cy, text=res, anchor="w", font=self.f_dim,
                                      fill=LIVE if res in ("DNF", "DSQ", "DNS") else FG_DIM,
                                      tags=("content", tag))
                    x = c.bbox(i)[2]
                    if (r.get("FastestLap") or {}).get("rank") == "1":
                        rr = 3.5 * u
                        c.create_oval(x + 6 * u, cy - rr, x + 6 * u + 2 * rr, cy + rr,
                                      fill="#b26bff", outline="", tags=("content", tag))
                        x += 6 * u + 2 * rr
                    return x
                x = chip(x, drv, tag, race)
        if nxt:
            tag = f"f1n{x:.0f}"

            def nxt_chip(x):
                i = c.create_text(x, cy, text="NEXT", anchor="w", font=self.f_status,
                                  fill=ACCENT, tags=("content", tag))
                x = c.bbox(i)[2] + 10 * u
                x = flag(x, tag)
                i = c.create_text(x, cy, text=f1_short(nxt.get("raceName")).upper(), anchor="w",
                                  font=self.f_abbr, fill=FG, tags=("content", tag))
                x = c.bbox(i)[2] + 10 * u
                st = f1_start(nxt)
                when = f"{local_day(st.isoformat())} · {local_time(st.isoformat())}" if st else \
                    nxt.get("date", "")
                i = c.create_text(x, cy, text=when, anchor="w", font=self.f_status, fill=ACCENT,
                                  tags=("content", tag))
                return c.bbox(i)[2]
            x = chip(x, nxt_chip, tag, nxt)
        return x

    def open_f1(self, race):
        key = ("f1", f"{race.get('season')}-{race.get('round')}")
        win = self.detail_windows.get(key)
        if win and win.alive:
            win.top.deiconify()
            win.top.lift()
            return
        self.detail_windows[key] = F1Window(self, race, key)

    def _look_ahead(self, league, day):
        """No games on this date: ask ESPN's default scoreboard (current week or
        matchday) when the next game is, for the "Next games" hint."""
        token = self.fetch_token
        url = f"{ESPN_API}/{LEAGUES[league]['espn']}/scoreboard"

        def done(data):
            if token != self.fetch_token or self.games:
                return
            later = []
            for ev in data.get("events") or []:
                st = parse_utc(ev.get("date"))
                if st and st.astimezone().date() > day:
                    later.append(st.astimezone())
            if later:
                nxt = min(later)
                self.empty_next = "Next games: " + nxt.strftime("%a %b ") + str(nxt.day)
                self.redraw()
        self.worker.run(lambda: fetch_json(url), done, lambda e: None)

    def _on_error(self, err):
        if not self.games:
            self.status_msg = "Can't reach the scores feed — retrying…"
            self.redraw()
        self.refresh_job = self.root.after(30000, self.refresh)

    def _update_date_label(self):
        if self.week_label:
            self.date_lbl.configure(text=self.week_label)
            return
        try:
            d = datetime.strptime(self.shown_date, "%Y-%m-%d")
            label = d.strftime("%a %b ") + str(d.day)
        except Exception:
            label = ""
        if self.day is None:
            label = "Today · " + label if label else "Today"
        self.date_lbl.configure(text=label)

    # ---- drawing -----------------------------------------------------------
    def _schedule_redraw(self):
        if not self.redraw_job:
            self.redraw_job = self.root.after(150, self._do_redraw)

    def _do_redraw(self):
        self.redraw_job = None
        self.redraw()

    def _draw_game(self, g, x, cy):
        c = self.canvas
        tag = f"g{g['league']}_{g['id']}"
        tags = ("content", tag)
        kind = g["kind"]
        started = kind in ("live", "final") and g["away"]["score"] is not None
        x0 = x
        u = self.scale * K
        x += 14 * u

        def num(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        def team(t, other, x):
            img = self.logos.get(t["logo"], self.logo_px, cb=self._schedule_redraw)
            if img:
                c.create_image(x + self.logo_px / 2, cy, image=img, tags=tags)
                x += self.logo_px + 6 * u
            else:
                s = int(5 * u)
                c.create_rectangle(x, cy - s, x + 2 * s, cy + s, fill=t["color"], outline="",
                                   tags=tags)
                x += 2 * s + 6 * u
            sc, osc = num(t["score"]), num(other["score"])
            losing = started and sc is not None and osc is not None and sc < osc
            fg = FG_LOSER if (losing and kind == "final") else FG
            i = c.create_text(x, cy, text=t["abbrev"], anchor="w", font=self.f_abbr, fill=fg,
                              tags=tags)
            x = c.bbox(i)[2] + 6 * u
            if started:
                i = c.create_text(x, cy, text=str(t["score"]), anchor="w", font=self.f_score,
                                  fill=fg, tags=tags)
                x = c.bbox(i)[2]
            return x + 12 * u

        x = team(g["away"], g["home"], x)
        if not started:
            i = c.create_text(x - 6 * u, cy, text="@", anchor="w", font=self.f_dim,
                              fill=FG_DIM, tags=tags)
            x = c.bbox(i)[2] + 8 * u
        x = team(g["home"], g["away"], x)

        color = {"live": LIVE, "final": FG_DIM, "future": ACCENT, "ppd": "#d9a640"}[kind]
        if kind == "live":
            r = int(3 * u)
            c.create_oval(x, cy - r, x + 2 * r, cy + r, fill=LIVE, outline="", tags=tags)
            x += 2 * r + 5 * u
        i = c.create_text(x, cy, text=g["status"].upper(), anchor="w", font=self.f_status,
                          fill=color, tags=tags)
        x = c.bbox(i)[2] + 14 * u

        bg = c.create_rectangle(x0, 0, x, self.h, fill=BG, outline="", tags=tags + ("bg",))
        c.tag_lower(bg)
        c.create_line(x, 10 * u, x, self.h - 10 * u, fill=SEP, tags=("content",))
        c.tag_bind(tag, "<Button-1>", lambda e, gg=g: self.open_game(gg))
        c.tag_bind(tag, "<Enter>", lambda e, t=tag: self._hover(t, True))
        c.tag_bind(tag, "<Leave>", lambda e, t=tag: self._hover(t, False))
        return x + 1

    def _hover(self, tag, on):
        for item in self.canvas.find_withtag(tag):
            if "bg" in self.canvas.gettags(item):
                self.canvas.itemconfigure(item, fill=BG_HOVER if on else BG)
        self.canvas.configure(cursor="hand2" if on else "")

    def redraw(self):
        c = self.canvas
        c.delete("all")
        cy = self.h // 2
        cw = max(c.winfo_width(), 1)
        if self.league == "f1":
            has = bool(self.f1_live or (self.f1 and (self.f1.get("race") or self.f1.get("next"))))
            draw = self._draw_f1_seq
        else:
            has = bool(self.games)
            draw = self._draw_games_seq
        if not has:
            empty = self.status_msg.startswith("No ")
            x = 16 * self.scale * K
            if empty:   # small calendar icon
                s_ = 8 * self.scale * K
                c.create_rectangle(x, cy - s_, x + 2 * s_, cy + s_, outline=FG_DIM,
                                   width=max(1, int(1.5 * self.scale)))
                c.create_line(x, cy - s_ / 2.5, x + 2 * s_, cy - s_ / 2.5, fill=FG_DIM,
                              width=max(1, int(1.5 * self.scale)))
                x += 2 * s_ + 10 * self.scale * K
            i = c.create_text(x, cy, text=self.status_msg, anchor="w",
                              font=self.f_abbr if empty else self.f_dim,
                              fill=FG if empty else FG_DIM)
            if empty and getattr(self, "empty_next", ""):
                c.create_text(c.bbox(i)[2] + 18 * self.scale * K, cy, text=self.empty_next,
                              anchor="w", font=self.f_dim, fill=ACCENT)
            self.seq_w = 0
            self.scrolling = False
            return
        x = draw(0, cy)
        self.seq_w = x
        self.scrolling = bool(self.cfg["scroll"]) and self.seq_w > 0
        if self.scrolling:
            copies = int(cw // self.seq_w) + 2   # cover the bar plus one lap: seamless wrap
            for _ in range(copies - 1):
                x = draw(x, cy)
            self.offset %= self.seq_w
            c.move("content", -self.offset, 0)
        else:
            self.offset = 0

    def _draw_games_seq(self, x, cy):
        order = {"live": 0, "future": 1, "final": 2, "ppd": 3}
        for g in sorted(self.games, key=lambda g: (order[g["kind"]], g.get("start", ""))):
            x = self._draw_game(g, x, cy)
        return x

    def _set_paused(self, p):
        self.paused = p

    def _nudge(self, dx):
        if not self.scrolling or not self.seq_w:
            return
        self.offset += dx
        shift = dx
        if self.offset >= self.seq_w:
            self.offset -= self.seq_w
            shift -= self.seq_w
        elif self.offset < 0:
            self.offset += self.seq_w
            shift += self.seq_w
        self.canvas.move("content", -shift, 0)

    def _wheel(self, e):
        self._nudge(-e.delta // 2)

    def _animate(self):
        if self.scrolling and not self.paused:
            step = self.cfg["speed"] * 0.75 * self.scale
            self._nudge(-step if self.cfg.get("direction", "ltr") == "ltr" else step)
        self.root.after(16, self._animate)

    # ---- standings (shared by all stats windows, cached 10 minutes) ---------
    def get_standings(self, league, on_done, on_error):
        hit = self.standings_cache.get(league)
        if hit and (datetime.now() - hit[0]).total_seconds() < 600:
            on_done(hit[1])
            return

        def done(secs):
            self.standings_cache[league] = (datetime.now(), secs)
            on_done(secs)
        self.worker.run(lambda: fetch_standings(league), done, on_error)

    # ---- detail windows ----------------------------------------------------
    def open_game(self, g):
        key = (g["league"], g["id"])
        win = self.detail_windows.get(key)
        if win and win.alive:
            win.top.deiconify()
            win.top.lift()
            win.top.focus_force()
            return
        cls = NHLGameWindow if LEAGUES[g["league"]]["provider"] == "nhl" else EspnGameWindow
        self.detail_windows[key] = cls(self, g)


# ------------------------------------------------------------- table bits ---
def style_once(root):
    if getattr(root, "_st_styled", False):
        return
    root._st_styled = True
    st = ttk.Style(root)
    try:
        st.theme_use("clam")
    except tk.TclError:
        pass
    st.configure(".", background=BG_PANEL, foreground=FG, fieldbackground=BG,
                 font=("Segoe UI", 9))
    st.configure("TNotebook", background=BG, borderwidth=0)
    st.configure("TNotebook.Tab", background=BG_PANEL, foreground=FG_DIM,
                 padding=(14, 6), font=("Segoe UI", 10, "bold"))
    st.map("TNotebook.Tab", background=[("selected", "#223047")],
           foreground=[("selected", FG)])
    st.configure("Treeview", background=BG, fieldbackground=BG, foreground=FG,
                 rowheight=22, borderwidth=0)
    st.map("Treeview", background=[("selected", "#2a4466")])
    st.configure("Treeview.Heading", background="#1c2533", foreground=FG_DIM,
                 font=("Segoe UI", 9, "bold"), relief="flat")
    st.map("Treeview.Heading", background=[("active", "#26344a")])
    st.configure("TFrame", background=BG_PANEL)
    st.configure("Group.TLabel", background=BG_PANEL, foreground=ACCENT,
                 font=("Segoe UI", 10, "bold"))
    st.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG,
                 arrowcolor=FG_DIM, bordercolor=BG)


LEFT_KEYS = ("name", "team", "desc", "goal", "stat", "player", "play")
STRETCH_KEYS = ("name", "goal", "desc", "player", "stat", "play")


def make_tree(parent, cols, height, sortable=True, scrollbar=True):
    frame = ttk.Frame(parent)
    tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings",
                        height=height, selectmode="browse")
    for key, head, width in cols:
        anchor = "w" if key in LEFT_KEYS else "center"
        tree.heading(key, text=head, anchor=anchor,
                     command=(lambda k=key: sort_tree(tree, k)) if sortable else "")
        tree.column(key, width=int(width), minwidth=30, anchor=anchor,
                    stretch=key in STRETCH_KEYS)
    tree.pack(side="left", fill="both", expand=True)
    if scrollbar:
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
    tree.tag_configure("odd", background="#121924")
    tree.tag_configure("total", foreground=ACCENT)
    return frame, tree


def sort_tree(tree, col):
    rev = getattr(tree, "_sort", (None, False))
    descending = not rev[1] if rev[0] == col else True
    kids = [k for k in tree.get_children("") if "total" not in tree.item(k, "tags")]
    totals = [k for k in tree.get_children("") if "total" in tree.item(k, "tags")]
    rows = [(tree.set(k, col), k) for k in kids]

    def key(v):
        s = v[0]
        if re.fullmatch(r"\d+:\d\d", s):
            return (0, toi_seconds(s))
        try:
            return (0, float(s.replace("%", "").replace("+", "")))
        except ValueError:
            return (1, s.lower())
    if col in ("name", "pos") and rev[0] != col:
        descending = False
    rows.sort(key=key, reverse=descending)
    for i, (_, k) in enumerate(rows):
        tree.move(k, "", i)
        hl = ("hl",) if "hl" in tree.item(k, "tags") else ()
        tree.item(k, tags=(("odd",) if i % 2 else ()) + hl)
    for k in totals:
        tree.move(k, "", "end")
    tree._sort = (col, descending)


def fill_tree(tree, rows, totals=None):
    tree.delete(*tree.get_children())
    for i, r in enumerate(rows):
        tree.insert("", "end", values=r, tags=("odd",) if i % 2 else ())
    if totals:
        tree.insert("", "end", values=totals, tags=("total",))
    s = getattr(tree, "_sort", None)
    if s and s[0]:
        tree._sort = (s[0], not s[1])
        sort_tree(tree, s[0])


def set_columns(tree, cols):
    """Reconfigure a Treeview's columns: cols = [(key, heading, width), ...]."""
    tree.configure(columns=[c[0] for c in cols])
    for key, head, width in cols:
        anchor = "w" if key in LEFT_KEYS else "center"
        tree.heading(key, text=head, anchor=anchor)
        tree.column(key, width=int(width), minwidth=28, anchor=anchor,
                    stretch=key in STRETCH_KEYS)


class ScrollFrame(ttk.Frame):
    """A vertically scrollable area for stacking several stat tables."""

    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, bg=BG_PANEL, highlightthickness=0)
        sb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>",
                        lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self.win, width=e.width))
        self.canvas.configure(yscrollcommand=sb.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.bind("<Enter>", lambda e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", lambda e: self.unbind_all("<MouseWheel>"))

    def _wheel(self, e):
        self.canvas.yview_scroll(int(-e.delta / 120), "units")


# -------------------------------------------------------------- standings ---
# Each league's standings become a list of sections:
#   [(title, columns, rows, team_keys)]  with columns = [(key, heading, width)]
#   and team_keys = the abbreviation/name strings of each row, for highlighting.

NHL_STANDINGS_COLS = [("rk", "#", 34), ("team", "Team", 200), ("gp", "GP", 40), ("w", "W", 40),
                      ("l", "L", 40), ("otl", "OTL", 44), ("pts", "PTS", 46), ("pct", "P%", 54),
                      ("rw", "RW", 40), ("gf", "GF", 44), ("ga", "GA", 44), ("diff", "DIFF", 50),
                      ("l10", "L10", 66), ("strk", "STRK", 52)]


def nhl_standings_sections(data):
    groups = {}
    for t in data.get("standings") or []:
        div = txt(t.get("divisionName")) or "League"
        conf = txt(t.get("conferenceName"))
        groups.setdefault((conf, div), []).append(t)
    out = []
    for (conf, div), teams in sorted(groups.items()):
        teams.sort(key=lambda t: (t.get("divisionSequence") or 99, -(t.get("points") or 0)))
        rows, keys = [], []
        for i, t in enumerate(teams, 1):
            ab = txt(t.get("teamAbbrev"))
            diff = t.get("goalDifferential")
            if diff is None and t.get("goalFor") is not None:
                diff = (t.get("goalFor") or 0) - (t.get("goalAgainst") or 0)
            l10 = f"{t.get('l10Wins', 0)}-{t.get('l10Losses', 0)}-{t.get('l10OtLosses', 0)}" \
                if t.get("l10Wins") is not None else ""
            strk = f"{t.get('streakCode', '')}{t.get('streakCount', '')}"
            rows.append((i, NHL_TEAM_NAMES.get(ab) or txt(t.get("teamName")) or ab,
                         t.get("gamesPlayed", ""), t.get("wins", ""), t.get("losses", ""),
                         t.get("otLosses", ""), t.get("points", ""),
                         fmt_pct(t.get("pointPctg"), False) if t.get("pointPctg") is not None else "",
                         t.get("regulationWins", ""), t.get("goalFor", ""), t.get("goalAgainst", ""),
                         (f"+{diff}" if isinstance(diff, int) and diff > 0 else diff)
                         if diff is not None else "", l10, strk))
            keys.append(ab)
        title = f"{div} Division" if div != "League" else "League"
        if conf:
            title += f"  ·  {conf} Conference"
        out.append((title, NHL_STANDINGS_COLS, rows, keys))
    return out


ESPN_STANDINGS_STATS = {
    "nfl": ["wins", "losses", "ties", "winPercent", "pointsFor", "pointsAgainst",
            "differential", "streak"],
    "mlb": ["wins", "losses", "winPercent", "gamesBehind", "pointsFor", "pointsAgainst",
            "differential", "streak"],
    "nba": ["wins", "losses", "winPercent", "gamesBehind", "avgPointsFor", "avgPointsAgainst",
            "differential", "streak"],
    "bun": ["gamesPlayed", "wins", "ties", "losses", "pointsFor", "pointsAgainst",
            "pointDifferential", "points"],
}
STAT_HEADS = {"wins": "W", "losses": "L", "ties": "T" , "winPercent": "PCT", "pointsFor": "PF",
              "pointsAgainst": "PA", "differential": "DIFF", "streak": "STRK",
              "gamesBehind": "GB", "avgPointsFor": "PPG", "avgPointsAgainst": "OPP PPG",
              "gamesPlayed": "GP", "pointDifferential": "GD", "points": "PTS"}
LEAGUE_HEADS = {"mlb": {"pointsFor": "RS", "pointsAgainst": "RA"},
                "bun": {"ties": "D", "pointsFor": "GF", "pointsAgainst": "GA"}}


def espn_standings_sections(data, league):
    found = []

    def visit(node):
        entries = (node.get("standings") or {}).get("entries")
        if entries:
            found.append((node.get("name") or node.get("abbreviation") or "Standings", entries))
        for ch in node.get("children") or []:
            visit(ch)
    visit(data)
    out = []
    for title, entries in found:
        def stats_of(e):
            return {st.get("name") or st.get("type"): st for st in e.get("stats") or []}
        first = stats_of(entries[0])
        wanted = [k for k in ESPN_STANDINGS_STATS.get(league, []) if k in first]
        if not wanted:
            wanted = [k for k, st in list(first.items())[:8] if st.get("displayValue") is not None]
        heads = {**STAT_HEADS, **LEAGUE_HEADS.get(league, {})}

        def val(e, k):
            st = stats_of(e).get(k) or {}
            v = st.get("value")
            return v if isinstance(v, (int, float)) else 0

        if league == "bun":
            if all("rank" in stats_of(e) for e in entries):
                entries = sorted(entries, key=lambda e: val(e, "rank"))
            else:
                entries = sorted(entries, key=lambda e: (-val(e, "points"),
                                                         -val(e, "pointDifferential")))
        else:
            entries = sorted(entries, key=lambda e: (-val(e, "winPercent"), -val(e, "wins")))
        cols = [("rk", "#", 34), ("team", "Team", 220)] + \
            [(f"s{i}", heads.get(k) or (first[k].get("abbreviation") or k[:5]).upper(), 58)
             for i, k in enumerate(wanted)]
        rows, keys = [], []
        for i, e in enumerate(entries, 1):
            tm = e.get("team") or {}
            st = stats_of(e)
            rows.append([i, tm.get("displayName") or tm.get("name", "")] +
                        [(st.get(k) or {}).get("displayValue", "") for k in wanted])
            keys.append(tm.get("abbreviation", ""))
        out.append((title, cols, rows, keys))
    return out


def fetch_standings(league):
    lg = LEAGUES[league]
    if lg["provider"] == "nhl":
        return nhl_standings_sections(fetch_json(f"{NHL_API}/standings/now"))
    base = f"https://site.api.espn.com/apis/v2/sports/{lg['espn']}/standings"
    if league in ("nfl", "mlb"):      # divisions rather than whole conferences/leagues
        try:
            secs = espn_standings_sections(fetch_json(base + "?level=3"), league)
            if secs:
                return secs
        except Exception:
            pass
    return espn_standings_sections(fetch_json(base), league)


# --------------------------------------------------------- game windows ----
class BaseGameWindow:
    """Shared header (logos, score, status, highlights) for every league."""

    def __init__(self, ticker, game):
        self.ticker = ticker
        self.game = game
        self.key = (game["league"], game["id"])
        self.alive = True
        self.job = None
        root = ticker.root
        style_once(root)

        self.top = tk.Toplevel(root, bg=BG)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(int(1100 * ticker.scale), sw - 40), min(int(780 * ticker.scale), sh - 80)
        self.top.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.top.minsize(760, 520)
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.attributes("-topmost", True)
        self.top.after(400, lambda: self.alive and self.top.attributes("-topmost", False))

        hdr = tk.Frame(self.top, bg=BG, pady=10)
        hdr.pack(fill="x")
        self.h_away = self._team_block(hdr, "left")
        mid = tk.Frame(hdr, bg=BG)
        mid.pack(side="left", expand=True)
        self.h_league = tk.Label(mid, text="", font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM)
        self.h_league.pack()
        self.h_score = tk.Label(mid, text="–", font=("Segoe UI", 30, "bold"), bg=BG, fg=FG)
        self.h_score.pack()
        self.h_status = tk.Label(mid, text="", font=("Segoe UI", 11, "bold"), bg=BG, fg=ACCENT)
        self.h_status.pack()
        self.h_info = tk.Label(mid, text="", font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        self.h_info.pack()
        self.yt_row = tk.Frame(mid, bg=BG)
        self.yt_row.pack(pady=(6, 0))
        self.yt_key = None
        self.h_home = self._team_block(hdr, "right")

        self.nb = ttk.Notebook(self.top)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.msg = tk.Label(self.top, text="Loading game stats…", bg=BG, fg=FG_DIM,
                            font=("Segoe UI", 9))
        self.msg.pack(side="bottom", fill="x", pady=(0, 6))

        self.build_tabs()
        self.standings_tab = ScrollFrame(self.nb)
        self.nb.add(self.standings_tab, text="Standings")
        self.standings_msg = ttk.Label(self.standings_tab.inner, text="Loading standings…",
                                       style="Group.TLabel")
        self.standings_msg.pack(anchor="w", padx=6, pady=10)
        self.update_header(game)
        self.load()
        self.ticker.get_standings(game["league"], self._show_standings, self._standings_error)

    # -- header --
    def _team_block(self, parent, side):
        fr = tk.Frame(parent, bg=BG, padx=30)
        fr.pack(side=side)
        logo = tk.Label(fr, bg=FG_DIM, width=2, height=3)
        abbr = tk.Label(fr, text="", font=("Segoe UI", 22, "bold"), bg=BG, fg=FG)
        name = tk.Label(fr, text="", font=("Segoe UI", 10), bg=BG, fg=FG_DIM)
        extra = tk.Label(fr, text="", font=("Segoe UI", 9), bg=BG, fg=FG_DIM)
        if side == "left":
            logo.grid(row=0, column=0, rowspan=3, padx=(0, 12))
            for i, w in enumerate((abbr, name, extra)):
                w.grid(row=i, column=1, sticky="w")
        else:
            logo.grid(row=0, column=1, rowspan=3, padx=(12, 0))
            for i, w in enumerate((abbr, name, extra)):
                w.grid(row=i, column=0, sticky="e")
        return logo, abbr, name, extra

    def _set_team(self, block, t):
        logo, abbr, name, extra = block
        size = int(64 * self.ticker.scale)
        img = self.ticker.logos.get(t.get("logo"), size,
                                    cb=lambda: self.alive and self._set_team(block, t))
        if img:
            logo.configure(image=img, bg=BG, width=0, height=0)
            logo.image = img
        else:
            logo.configure(bg=t.get("color", FG_DIM))
        abbr.configure(text=t.get("abbrev", ""))
        name.configure(text=t.get("name", ""))
        extra.configure(text=t.get("extra", ""))

    def update_header(self, g):
        if not self.alive:
            return
        self.game = {**self.game, **{k: v for k, v in g.items() if v not in (None, "", [])}}
        g = self.game
        self._set_team(self.h_away, g["away"])
        self._set_team(self.h_home, g["home"])
        kind = g["kind"]
        self.h_league.configure(text=LEAGUES[g["league"]]["name"].upper())
        if kind in ("live", "final") and g["away"]["score"] is not None:
            self.h_score.configure(text=f"{g['away']['score']}  –  {g['home']['score']}")
        else:
            self.h_score.configure(text="vs")
        self.h_status.configure(text=g["status"].upper(),
                                fg={"live": LIVE, "final": FG_DIM}.get(kind, ACCENT))
        bits = []
        if g.get("start"):
            bits.append(f"{local_day(g['start'])} · {local_time(g['start'])}")
        if g.get("venue"):
            bits.append(g["venue"])
        if g.get("tv"):
            bits.append("TV: " + ", ".join(g["tv"]))
        self.h_info.configure(text="   ·   ".join(bits))
        self._update_yt_buttons(g, kind == "final")
        aa, ha = g["away"]["abbrev"], g["home"]["abbrev"]
        self.top.title(f"{aa} @ {ha} — {g['status']}")
        self.on_header(g)

    def on_header(self, g):
        pass

    # -- highlights --
    def _update_yt_buttons(self, g, final):
        key = (final, g["away"]["abbrev"], g["home"]["abbrev"])
        if key == self.yt_key:
            return
        self.yt_key = key
        for w in self.yt_row.winfo_children():
            w.destroy()
        if not final:
            return
        for side in ("away", "home"):
            nick = g[side]["short"] or g[side]["abbrev"]
            b = tk.Label(self.yt_row, text=f"▶  {nick} highlights", bg="#e62117", fg="white",
                         font=("Segoe UI", 9, "bold"), padx=10, pady=3, cursor="hand2")
            b.pack(side="left", padx=4)
            b.bind("<Button-1>", lambda e, s=side, w=b, n=nick: self._play_highlights(s, w, n))
            b.bind("<Enter>", lambda e, w=b: w.configure(bg="#ff3d33"))
            b.bind("<Leave>", lambda e, w=b: w.configure(bg="#e62117"))
        self.yt_tip = tk.Label(self.yt_row, text="plays on YouTube", bg=BG, fg=FG_DIM,
                               font=("Segoe UI", 8))
        self.yt_tip.pack(side="left", padx=4)

    def _play_highlights(self, side, btn, nick):
        if getattr(btn, "_busy", False):
            return
        btn._busy = True
        btn.configure(text="  Finding video…  ")
        cache = self.ticker.cfg.setdefault("yt_channels", {})
        info = highlight_info(self.game, side)

        def done(res):
            url, source = res
            btn._busy = False
            if self.alive:
                btn.configure(text=f"▶  {nick} highlights")
                self.yt_tip.configure(
                    text="video not posted yet — showing YouTube search" if source == "search"
                    else f"playing from {source}")
            save_config(self.ticker.cfg)
            webbrowser.open(url)

        self.ticker.worker.run(lambda: find_highlight_video(info, cache), done,
                               lambda e: done((highlights_search_url(info), "search")))

    # -- standings --
    def _standings_error(self, e):
        if self.alive:
            self.standings_msg.configure(text="Couldn't load standings right now. "
                                              "Reopen the game to try again.")

    def _show_standings(self, sections):
        if not self.alive:
            return
        mine = {self.game["away"]["abbrev"], self.game["home"]["abbrev"]}
        inner = self.standings_tab.inner
        for w in inner.winfo_children():
            w.destroy()
        if not sections:
            ttk.Label(inner, text="Standings aren't available for this league right now.",
                      style="Group.TLabel").pack(anchor="w", padx=6, pady=10)
            return
        # Groups containing this game's teams come first.
        ordered = sorted(sections, key=lambda sec: 0 if mine & set(sec[3]) else 1)
        ttk.Label(inner, text=f"{LEAGUES[self.game['league']]['name']} standings   ·   "
                              f"{self.game['away']['abbrev']} and {self.game['home']['abbrev']} "
                              f"highlighted   ·   click a column to sort",
                  background=BG_PANEL, foreground=FG_DIM).pack(anchor="w", padx=6, pady=(8, 0))
        for title, cols, rows, keys in ordered:
            ttk.Label(inner, text=title, style="Group.TLabel").pack(anchor="w", padx=4,
                                                                    pady=(12, 2))
            fr, tree = make_tree(inner, cols, max(2, min(len(rows), 20)),
                                 scrollbar=len(rows) > 20)
            fr.pack(fill="x", padx=4)
            tree.tag_configure("hl", foreground="#ffd166", font=("Segoe UI", 9, "bold"))
            for i, (r, k) in enumerate(zip(rows, keys)):
                tags = (("odd",) if i % 2 else ()) + (("hl",) if k in mine else ())
                tree.insert("", "end", values=r, tags=tags)

    # -- loading --
    def build_tabs(self):
        raise NotImplementedError

    def fetch(self):
        raise NotImplementedError

    def apply(self, data):
        raise NotImplementedError

    def load(self):
        self.ticker.worker.run(self.fetch, self._on_data, self._on_error)

    def _schedule(self, live):
        if self.alive:
            self.job = self.top.after(20000 if live else 300000, self.load)

    def _on_error(self, e):
        if not self.alive:
            return
        self.msg.configure(text=f"Couldn't load game data ({e.__class__.__name__}). Retrying…",
                           fg=LIVE)
        self._schedule(True)

    def _on_data(self, data):
        if not self.alive:
            return
        has_stats = self.apply(data)
        live = self.game["kind"] == "live"
        if not has_stats:
            self.msg.configure(text="Player stats will appear once the game starts.", fg=FG_DIM)
        else:
            stamp = datetime.now().strftime("%I:%M:%S %p").lstrip("0")
            self.msg.configure(text=("Live — auto-updating every 20 s · " if live else "")
                               + f"Updated {stamp}", fg=GOOD if live else FG_DIM)
        self._schedule(live)

    def close(self):
        self.alive = False
        if self.job:
            try:
                self.top.after_cancel(self.job)
            except tk.TclError:
                pass
        self.top.destroy()
        self.ticker.detail_windows.pop(self.key, None)


# ---------------------------------------------------------- NHL window ----
SKATER_COLS = [
    ("num", "#", 36), ("name", "Player", 170), ("pos", "Pos", 40), ("g", "G", 34),
    ("a", "A", 34), ("p", "P", 34), ("pm", "+/-", 40), ("sog", "SOG", 44),
    ("hits", "HIT", 40), ("blk", "BLK", 40), ("pim", "PIM", 40), ("ppg", "PPG", 40),
    ("fo", "FO%", 56), ("toi", "TOI", 56), ("shifts", "SHF", 40), ("gv", "GV", 36),
    ("tk", "TK", 36),
]
GOALIE_COLS = [
    ("num", "#", 36), ("name", "Goalie", 170), ("sa", "SA", 44), ("sv", "SV", 44),
    ("ga", "GA", 44), ("svp", "SV%", 56), ("ev", "EV SV", 64), ("pp", "PP SV", 64),
    ("sh", "SH SV", 64), ("toi", "TOI", 56), ("dec", "Dec", 44), ("pim", "PIM", 40),
]
NHL_STAT_LABELS = {
    "sog": "Shots on goal", "faceoffWinningPctg": "Faceoff %", "powerPlay": "Power play",
    "powerPlayPctg": "Power play %", "pim": "Penalty minutes", "hits": "Hits",
    "blockedShots": "Blocked shots", "giveaways": "Giveaways", "takeaways": "Takeaways",
}


class NHLGameWindow(BaseGameWindow):
    def build_tabs(self):
        summ = ttk.Frame(self.nb, padding=8)
        self.nb.add(summ, text="Game summary")
        summ.columnconfigure(0, weight=2, uniform="sc")
        summ.columnconfigure(1, weight=3, uniform="sc")
        summ.rowconfigure(1, weight=1)
        summ.rowconfigure(2, weight=1)
        f, self.t_line = make_tree(summ, [("team", "Team", 120)], 2, sortable=False)
        f.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))
        f, self.t_stars = make_tree(summ, [("star", "★", 50), ("player", "Three stars", 200),
                                           ("team", "Team", 60), ("line", "Line", 120)],
                                    3, sortable=False)
        f.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        f, self.t_team = make_tree(summ, [("stat", "Team stats", 150), ("away", "AWY", 80),
                                          ("home", "HOM", 80)], 9, sortable=False)
        f.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))
        f, self.t_goals = make_tree(summ, [("per", "Per", 44), ("time", "Time", 54),
                                           ("team", "Team", 54), ("goal", "Goal (assists)", 340),
                                           ("str", "Str", 48), ("score", "Score", 60)],
                                    9, sortable=False)
        f.grid(row=1, column=1, sticky="nsew", pady=(0, 8))
        f, self.t_pens = make_tree(summ, [("per", "Per", 44), ("time", "Time", 54),
                                          ("team", "Team", 54), ("player", "Player", 180),
                                          ("desc", "Infraction", 260), ("min", "Min", 44)],
                                   6, sortable=False)
        f.grid(row=2, column=0, columnspan=2, sticky="nsew")

        self.player_tabs = {}
        for side in ("awayTeam", "homeTeam"):
            fr = ttk.Frame(self.nb, padding=8)
            self.nb.add(fr, text=side)
            fr.rowconfigure(0, weight=3)
            fr.rowconfigure(1, weight=1)
            fr.columnconfigure(0, weight=1)
            sf, st = make_tree(fr, SKATER_COLS, 14)
            sf.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
            gf, gt = make_tree(fr, GOALIE_COLS, 3)
            gf.grid(row=1, column=0, sticky="nsew")
            self.player_tabs[side] = (fr, st, gt)

    def on_header(self, g):
        aa, ha = g["away"]["abbrev"], g["home"]["abbrev"]
        self.nb.tab(self.player_tabs["awayTeam"][0], text=f"{aa} players")
        self.nb.tab(self.player_tabs["homeTeam"][0], text=f"{ha} players")
        self.t_team.heading("away", text=aa)
        self.t_team.heading("home", text=ha)

    def fetch(self):
        gid = self.game["id"]
        out = {"box": fetch_json(f"{NHL_API}/gamecenter/{gid}/boxscore")}
        for key, path in (("landing", "landing"), ("rail", "right-rail")):
            try:
                out[key] = fetch_json(f"{NHL_API}/gamecenter/{gid}/{path}")
            except Exception:
                out[key] = {}
        return out

    def apply(self, d):
        box, landing, rail = d["box"], d.get("landing") or {}, d.get("rail") or {}
        merged = dict(self.game["raw"])
        merged.update({k: v for k, v in box.items() if v is not None})
        for k in ("venue", "tvBroadcasts", "startTimeUTC"):
            if not merged.get(k) and landing.get(k):
                merged[k] = landing[k]
        self.update_header(nhl_normalize(merged))
        summary = landing.get("summary") or {}
        away = box.get("awayTeam", {}).get("abbrev") or self.game["away"]["abbrev"]
        home = box.get("homeTeam", {}).get("abbrev") or self.game["home"]["abbrev"]
        self._fill_linescore(rail, summary, box, away, home)
        self._fill_team_stats(rail, box)
        self._fill_goals(summary)
        self._fill_penalties(summary)
        self._fill_stars(summary)
        pbgs = box.get("playerByGameStats") or {}
        for side in ("awayTeam", "homeTeam"):
            self._fill_players(side, pbgs.get(side) or {})
        return bool(pbgs)

    def _fill_linescore(self, rail, summary, box, away, home):
        ls = rail.get("linescore") or summary.get("linescore") or {}
        periods = ls.get("byPeriod") or []
        tot = ls.get("totals") or {}
        if not periods:
            counts = {}
            for p in summary.get("scoring") or []:
                lab = nhl_period_label(p.get("periodDescriptor"))
                a = h = 0
                for gl in p.get("goals") or []:
                    if txt(gl.get("teamAbbrev")) == away:
                        a += 1
                    else:
                        h += 1
                counts[lab] = (a, h)
            n = max(3, (box.get("periodDescriptor") or {}).get("number") or 0)
            labs = [ordinal(i) for i in range(1, min(n, 3) + 1)]
            labs += [lb for lb in counts if lb not in labs]
            periods = [{"periodDescriptor": {"label": lb}, "away": counts.get(lb, (0, 0))[0],
                        "home": counts.get(lb, (0, 0))[1]} for lb in labs]
            tot = {"away": box.get("awayTeam", {}).get("score", ""),
                   "home": box.get("homeTeam", {}).get("score", "")}
        labels = [p["periodDescriptor"].get("label") or nhl_period_label(p["periodDescriptor"])
                  for p in periods]
        set_columns(self.t_line, [("team", "Team", 110)] +
                    [(f"p{i}", lb, 48) for i, lb in enumerate(labels)] + [("T", "T", 48)])
        fill_tree(self.t_line,
                  [[away] + [p.get("away", "") for p in periods] + [tot.get("away", "")],
                   [home] + [p.get("home", "") for p in periods] + [tot.get("home", "")]])

    def _fill_team_stats(self, rail, box):
        rows = []
        for s in rail.get("teamGameStats") or []:
            cat = s.get("category", "")
            av, hv = s.get("awayValue", ""), s.get("homeValue", "")
            if cat.endswith("Pctg"):
                av, hv = fmt_pct(av), fmt_pct(hv)
            rows.append((NHL_STAT_LABELS.get(cat, cat), av, hv))
        if not rows:
            pb = box.get("playerByGameStats") or {}
            if pb:
                def tot(side, key):
                    team = pb.get(side) or {}
                    return sum(int(p.get(key) or 0) for grp in ("forwards", "defense")
                               for p in team.get(grp) or [])
                for key, label in (("sog", "Shots on goal"), ("hits", "Hits"),
                                   ("blockedShots", "Blocked shots"), ("pim", "Penalty minutes"),
                                   ("powerPlayGoals", "Power-play goals"),
                                   ("giveaways", "Giveaways"), ("takeaways", "Takeaways")):
                    rows.append((label, tot("awayTeam", key), tot("homeTeam", key)))
        fill_tree(self.t_team, rows or [("No team stats yet", "", "")])

    def _fill_goals(self, summary):
        rows = []
        for p in summary.get("scoring") or []:
            lab = nhl_period_label(p.get("periodDescriptor"))
            for gl in p.get("goals") or []:
                scorer = person(gl)
                if gl.get("goalsToDate"):
                    scorer += f" ({gl['goalsToDate']})"
                assists = ", ".join(person(a) for a in gl.get("assists") or [])
                desc = scorer + (f"  —  {assists}" if assists else "  —  unassisted")
                mod = gl.get("goalModifier", "none")
                if mod and mod != "none":
                    desc += f"  [{mod.replace('-', ' ')}]"
                strength = (gl.get("strength") or "").upper()
                rows.append((lab, gl.get("timeInPeriod", ""), txt(gl.get("teamAbbrev")),
                             desc, strength if strength != "EV" else "",
                             f"{gl.get('awayScore', '')}-{gl.get('homeScore', '')}"))
        fill_tree(self.t_goals, rows or [("", "", "", "No goals yet", "", "")])

    def _fill_penalties(self, summary):
        rows = []
        for p in summary.get("penalties") or []:
            lab = nhl_period_label(p.get("periodDescriptor"))
            for pen in p.get("penalties") or []:
                who = person(pen.get("committedByPlayer")) or txt(pen.get("servedBy")) or "Team"
                desc = (pen.get("descKey") or "").replace("-", " ").capitalize()
                if pen.get("drawnBy"):
                    desc += f" (drawn by {person(pen['drawnBy'])})"
                rows.append((lab, pen.get("timeInPeriod", ""), txt(pen.get("teamAbbrev")),
                             who, desc, pen.get("duration", "")))
        fill_tree(self.t_pens, rows or [("", "", "", "No penalties", "", "")])

    def _fill_stars(self, summary):
        rows = []
        for s in summary.get("threeStars") or []:
            if s.get("position") == "G" and s.get("savePctg") is not None:
                line = f"{fmt_pct(s['savePctg'], False)} SV%"
            else:
                line = f"{s.get('goals', 0)}G  {s.get('assists', 0)}A  {s.get('points', 0)}P"
            rows.append(("★" * int(s.get("star") or 1), person(s), txt(s.get("teamAbbrev")), line))
        fill_tree(self.t_stars, rows or [("", "Announced after the game", "", "")])

    def _fill_players(self, side, team):
        _, st, gt = self.player_tabs[side]
        rows = []
        for grp in ("forwards", "defense"):
            for p in team.get(grp) or []:
                pm = p.get("plusMinus", 0) or 0
                fo = p.get("faceoffWinningPctg")
                rows.append((
                    p.get("sweaterNumber", ""), person(p), p.get("position", ""),
                    p.get("goals", 0), p.get("assists", 0), p.get("points", 0),
                    f"+{pm}" if pm > 0 else pm, p.get("sog", 0), p.get("hits", 0),
                    p.get("blockedShots", 0), p.get("pim", 0), p.get("powerPlayGoals", 0),
                    fmt_pct(fo) if fo else "", p.get("toi", ""), p.get("shifts", ""),
                    p.get("giveaways", 0), p.get("takeaways", 0)))
        if not getattr(st, "_sort", None):
            st._sort = ("p", True)   # default: points, high to low
        fill_tree(st, rows)
        grows = []
        for p in team.get("goalies") or []:
            sa, sv = p.get("shotsAgainst"), p.get("saves")
            if (sa is None or sv is None) and p.get("saveShotsAgainst"):
                try:
                    sv, sa = (int(x) for x in p["saveShotsAgainst"].split("/"))
                except ValueError:
                    pass
            if p.get("toi") in (None, "00:00") and not sa:
                continue
            grows.append((
                p.get("sweaterNumber", ""), person(p) + ("  (S)" if p.get("starter") else ""),
                sa if sa is not None else "", sv if sv is not None else "",
                p.get("goalsAgainst", ""),
                fmt_pct(p.get("savePctg"), False) if p.get("savePctg") is not None else "",
                p.get("evenStrengthShotsAgainst", ""), p.get("powerPlayShotsAgainst", ""),
                p.get("shorthandedShotsAgainst", ""), p.get("toi", ""),
                p.get("decision", ""), p.get("pim", 0)))
        fill_tree(gt, grows)


# ------------------------------------------- ESPN window (NFL/MLB/NBA/soccer) --
def period_labels(league, n):
    if league in ("nfl", "nba"):
        return [f"Q{i}" if i <= 4 else ("OT" if i == 5 else f"OT{i - 4}")
                for i in range(1, n + 1)]
    if league == "bun":
        return (["1st", "2nd", "ET1", "ET2", "PK"] + [str(i) for i in range(6, n + 1)])[:n]
    return [str(i) for i in range(1, n + 1)]   # MLB innings


class EspnGameWindow(BaseGameWindow):
    def build_tabs(self):
        league = self.game["league"]
        summ = ttk.Frame(self.nb, padding=8)
        self.nb.add(summ, text="Game summary")
        summ.columnconfigure(0, weight=2, uniform="sc")
        summ.columnconfigure(1, weight=3, uniform="sc")
        summ.rowconfigure(1, weight=1)
        f, self.t_line = make_tree(summ, [("team", "Team", 120)], 2, sortable=False,
                                   scrollbar=False)
        f.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 8))
        f, self.t_team = make_tree(summ, [("stat", "Team stats", 170), ("away", "AWY", 90),
                                          ("home", "HOM", 90)], 14, sortable=False)
        f.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        title = {"bun": "Key events", "nba": "Game leaders"}.get(league, "Scoring plays")
        f, self.t_plays = make_tree(summ, [("per", "Per", 50), ("time", "Time", 64),
                                           ("team", "Team", 60), ("play", title, 420),
                                           ("score", "Score", 64)], 14, sortable=False)
        f.grid(row=1, column=1, sticky="nsew")
        self.team_tabs = {}
        for side in ("away", "home"):
            sf = ScrollFrame(self.nb)
            self.nb.add(sf, text=side)
            self.team_tabs[side] = {"frame": sf, "groups": {}}

    def on_header(self, g):
        for side in ("away", "home"):
            self.nb.tab(self.team_tabs[side]["frame"], text=f"{g[side]['abbrev']} players")
        self.t_team.heading("away", text=g["away"]["abbrev"])
        self.t_team.heading("home", text=g["home"]["abbrev"])

    def fetch(self):
        path = LEAGUES[self.game["league"]]["espn"]
        return fetch_json(f"{ESPN_API}/{path}/summary?event={self.game['id']}")

    def apply(self, data):
        league = self.game["league"]
        header = data.get("header") or {}
        comp = (header.get("competitions") or [{}])[0]
        if comp.get("competitors"):
            ev = {"id": header.get("id") or self.game["id"], "date": comp.get("date")}
            g = espn_normalize(ev, league, comp)
            venue = ((data.get("gameInfo") or {}).get("venue") or {}).get("fullName")
            if venue:
                g["venue"] = venue
            g["raw"] = self.game["raw"]
            self.update_header(g)
        cs = comp.get("competitors") or []
        by_side = {c.get("homeAway"): c for c in cs}
        ids = {str((c.get("team") or {}).get("id", "")): c.get("homeAway") for c in cs}
        abbr = {side: self.game[side]["abbrev"] for side in ("away", "home")}
        self._fill_linescore(league, by_side, abbr)
        self._fill_team_stats(data.get("boxscore") or {}, ids, abbr)
        self._fill_plays(league, data, ids, abbr)
        any_players = False
        if league == "bun":
            for r in data.get("rosters") or []:
                side = r.get("homeAway") or ids.get(str((r.get("team") or {}).get("id", "")))
                if side in self.team_tabs:
                    any_players |= self._fill_soccer_roster(side, r.get("roster") or [])
        for p in (data.get("boxscore") or {}).get("players") or []:
            side = ids.get(str((p.get("team") or {}).get("id", ""))) or p.get("homeAway")
            if side in self.team_tabs:
                any_players |= self._fill_player_groups(side, p.get("statistics") or [])
        return any_players

    # -- summary tab --
    def _fill_linescore(self, league, by_side, abbr):
        lines = {s: [ls.get("displayValue", ls.get("value", "")) for ls in
                     (by_side.get(s) or {}).get("linescores") or []] for s in ("away", "home")}
        n = max(len(lines["away"]), len(lines["home"]))
        if league == "mlb":
            n = max(n, 9)
        labels = period_labels(league, n)
        extra = [("R", "R")] if league == "mlb" else [("T", "T")]
        if league == "mlb":
            extra += [("H", "H"), ("E", "E")]
        set_columns(self.t_line, [("team", "Team", 140)] +
                    [(f"p{i}", lb, 46) for i, lb in enumerate(labels)] +
                    [(k, h, 50) for k, h in extra])
        rows = []
        for s in ("away", "home"):
            c = by_side.get(s) or {}
            vals = lines[s] + [""] * (n - len(lines[s]))
            score = self.game[s]["score"]
            tail = [score if score is not None else ""]
            if league == "mlb":
                tail += [c.get("hits", ""), c.get("errors", "")]
            rows.append([abbr[s]] + vals + tail)
        fill_tree(self.t_line, rows)

    def _fill_team_stats(self, box, ids, abbr):
        per_side, order = {}, []
        for t in box.get("teams") or []:
            side = t.get("homeAway") or ids.get(str((t.get("team") or {}).get("id", "")))
            if side not in ("away", "home"):
                continue
            vals = {}
            for s in t.get("statistics") or []:
                if isinstance(s.get("stats"), list):     # MLB groups (batting, pitching...)
                    grp = s.get("displayName") or s.get("name", "").title()
                    for x in s["stats"][:10]:
                        k = f"{grp}:{x.get('name')}"
                        lab = f"{grp} · {x.get('displayName') or x.get('abbreviation') or x.get('name')}"
                        vals[k] = (lab, x.get("displayValue", ""))
                        if k not in order:
                            order.append(k)
                else:
                    k = s.get("name") or s.get("label")
                    vals[k] = (s.get("label") or s.get("displayName") or k,
                               s.get("displayValue", s.get("value", "")))
                    if k not in order:
                        order.append(k)
            per_side[side] = vals
        rows = []
        for k in order:
            a = per_side.get("away", {}).get(k)
            h = per_side.get("home", {}).get(k)
            lab = (a or h)[0]
            rows.append((lab, a[1] if a else "", h[1] if h else ""))
        fill_tree(self.t_team, rows or [("No team stats yet", "", "")])

    def _fill_plays(self, league, data, ids, abbr):
        def team_of(p):
            t = p.get("team") or {}
            side = ids.get(str(t.get("id", "")))
            return abbr.get(side) or t.get("abbreviation") or t.get("displayName", "")

        rows = []
        if league == "bun":
            for e in data.get("keyEvents") or []:
                kind = ((e.get("type") or {}).get("text") or "")
                if kind.lower() in ("kickoff", "halftime", "end regular time", "start 2nd half",
                                    "start extra time", "end extra time"):
                    continue
                per = (e.get("period") or {}).get("number", "")
                text = e.get("text") or kind
                if kind and not text.lower().startswith(kind.lower()):
                    text = f"{kind}: {text}"
                rows.append((period_labels("bun", max(int(per or 1), 1))[-1] if per else "",
                             (e.get("clock") or {}).get("displayValue", ""), team_of(e), text,
                             "⚽" if e.get("scoringPlay") else ""))
        else:
            plays = data.get("scoringPlays") or [p for p in data.get("plays") or []
                                                 if p.get("scoringPlay")]
            for p in plays:
                per = (p.get("period") or {}).get("number") or 0
                lab = period_labels(league, max(per, 1))[-1] if per else ""
                if league == "mlb" and per:
                    half = (p.get("period") or {}).get("type") or ""
                    lab = ("Top " if half.lower().startswith("top") else
                           "Bot " if half.lower().startswith("bot") else "") + ordinal(per)
                kind = (p.get("scoringType") or {}).get("displayName") or \
                    (p.get("type") or {}).get("text", "")
                text = p.get("text", "")
                if kind and league == "nfl":
                    text = f"{kind}: {text}"
                rows.append((lab, (p.get("clock") or {}).get("displayValue", "")
                             if league != "mlb" else "", team_of(p), text,
                             f"{p.get('awayScore', '')}-{p.get('homeScore', '')}"))
            if not rows:   # NBA (and fallbacks): game leaders instead
                for t in data.get("leaders") or []:
                    tm = team_of(t)
                    for cat in t.get("leaders") or []:
                        top = (cat.get("leaders") or [{}])[0]
                        who = (top.get("athlete") or {}).get("displayName", "")
                        if who:
                            rows.append((cat.get("shortDisplayName") or "", "", tm,
                                         f"{cat.get('displayName', '')}: {who} — "
                                         f"{top.get('displayValue', '')}", ""))
        empty = {"bun": "No key events yet", "nba": "Leaders appear once the game starts"}
        fill_tree(self.t_plays, rows or [("", "", "", empty.get(league, "No scoring yet"), "")])

    # -- player tabs --
    def _group_table(self, side, name, cols, nrows):
        tab = self.team_tabs[side]
        grp = tab["groups"].get(name)
        sig = tuple(c[1] for c in cols)
        if grp and grp["sig"] != sig:
            grp["label"].destroy()
            grp["frame"].destroy()
            grp = None
        if not grp:
            lbl = ttk.Label(tab["frame"].inner, text=name, style="Group.TLabel")
            lbl.pack(anchor="w", padx=4, pady=(10, 2))
            fr, tree = make_tree(tab["frame"].inner, cols, max(2, min(nrows, 16)),
                                 scrollbar=nrows > 16)
            fr.pack(fill="x", padx=4)
            grp = {"label": lbl, "frame": fr, "tree": tree, "sig": sig}
            tab["groups"][name] = grp
        else:
            grp["tree"].configure(height=max(2, min(nrows, 16)))
        return grp["tree"]

    def _fill_player_groups(self, side, stats):
        filled = False
        for grp in stats:
            athletes = grp.get("athletes") or []
            labels = grp.get("labels") or grp.get("names") or []
            if not athletes or not labels:
                continue
            name = (grp.get("displayName") or grp.get("name") or grp.get("text") or
                    "Players").replace("_", " ").title()
            cols = [("name", "Player", 190), ("pos", "Pos", 44)] + \
                [(f"c{i}", lb, max(46, 9 * len(lb))) for i, lb in enumerate(labels)]
            rows = []
            for a in athletes:
                ath = a.get("athlete") or {}
                st = a.get("stats") or []
                if not st and a.get("didNotPlay"):
                    st = ["DNP"] + [""] * (len(labels) - 1)
                nm = ath.get("displayName") or ath.get("shortName", "")
                if ath.get("jersey"):
                    nm = f"{nm}  #{ath['jersey']}"
                rows.append([nm, (ath.get("position") or {}).get("abbreviation", "")] +
                            list(st) + [""] * (len(labels) - len(st)))
            totals = grp.get("totals")
            tot = (["TEAM", ""] + list(totals)) if totals and any(totals) else None
            tree = self._group_table(side, name, cols, len(rows) + (1 if tot else 0))
            fill_tree(tree, rows, tot)
            filled = True
        return filled

    def _fill_soccer_roster(self, side, roster):
        if not roster:
            return False
        stat_keys, heads = [], []
        for p in roster:
            for s in p.get("stats") or []:
                k = s.get("name")
                if k and k not in stat_keys:
                    stat_keys.append(k)
                    heads.append(s.get("abbreviation") or s.get("shortDisplayName") or k[:4])
        cols = [("num", "#", 40), ("name", "Player", 200), ("pos", "Pos", 50)] + \
            [(f"c{i}", h, max(44, 9 * len(h))) for i, h in enumerate(heads)]
        for title, starters in (("Starting XI", True), ("Substitutes", False)):
            rows = []
            for p in roster:
                if bool(p.get("starter")) != starters:
                    continue
                ath = p.get("athlete") or {}
                vals = {s.get("name"): s.get("displayValue", s.get("value", ""))
                        for s in p.get("stats") or []}
                nm = ath.get("displayName", "")
                if not starters and p.get("subbedIn"):
                    nm += "  ↑"
                rows.append([p.get("jersey") or ath.get("jersey", ""), nm,
                             (p.get("position") or ath.get("position") or {}).get(
                                 "abbreviation", "")] + [vals.get(k, "") for k in stat_keys])
            if rows:
                tree = self._group_table(side, title, cols, len(rows))
                fill_tree(tree, rows)
        return True


# ------------------------------------------------------------ F1 window ----
class F1Window:
    """Race weekend window: results, sprint, qualifying, both championships,
    the weekend schedule, and a race-highlights button."""

    RESULT_COLS = [("pos", "Pos", 44), ("num", "No.", 44), ("name", "Driver", 190),
                   ("team", "Team", 150), ("laps", "Laps", 50), ("time", "Time / Gap", 120),
                   ("int", "Interval", 90), ("grid", "Grid", 46), ("gain", "+/–", 46),
                   ("pts", "Pts", 46), ("fl", "Fastest lap", 110)]

    def __init__(self, ticker, race, key):
        self.ticker, self.race, self.key = ticker, race, key
        self.alive = True
        root = ticker.root
        style_once(root)
        self.top = tk.Toplevel(root, bg=BG)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        w, h = min(int(1100 * ticker.scale), sw - 40), min(int(780 * ticker.scale), sh - 80)
        self.top.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
        self.top.minsize(760, 520)
        self.top.title(f"{race.get('season')} {race.get('raceName', 'F1')}")
        self.top.protocol("WM_DELETE_WINDOW", self.close)
        self.top.bind("<Escape>", lambda e: self.close())
        self.top.attributes("-topmost", True)
        self.top.after(400, lambda: self.alive and self.top.attributes("-topmost", False))

        circ = race.get("Circuit") or {}
        loc = circ.get("Location") or {}
        st = f1_start(race)
        hdr = tk.Frame(self.top, bg=BG, pady=10)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"FORMULA 1  ·  {race.get('season', '')}  ·  ROUND {race.get('round', '')}",
                 font=("Segoe UI", 9, "bold"), bg=BG, fg=FG_DIM).pack()
        tk.Label(hdr, text=race.get("raceName", ""), font=("Segoe UI", 24, "bold"), bg=BG,
                 fg=FG).pack()
        where = " · ".join(x for x in (circ.get("circuitName"),
                                       ", ".join(y for y in (loc.get("locality"),
                                                             loc.get("country")) if y)) if x)
        when = f"{local_day(st.isoformat())} · {local_time(st.isoformat())}" if st else ""
        tk.Label(hdr, text="   ·   ".join(x for x in (when, where) if x), font=("Segoe UI", 9),
                 bg=BG, fg=FG_DIM).pack()
        results = race.get("Results") or []
        self.summary = tk.Label(hdr, text="", font=("Segoe UI", 11, "bold"), bg=BG, fg=ACCENT)
        self.summary.pack(pady=(4, 0))
        if results:
            win = results[0]
            wd = win.get("Driver") or {}
            fl = next((r for r in results if (r.get("FastestLap") or {}).get("rank") == "1"), None)
            txt_ = f"Winner: {f1_full_name(wd)} ({(win.get('Constructor') or {}).get('name', '')})"
            if fl:
                txt_ += (f"      Fastest lap: {f1_full_name(fl.get('Driver') or {})} "
                         f"{(fl.get('FastestLap') or {}).get('Time', {}).get('time', '')}")
            self.summary.configure(text=txt_)
            yt = tk.Frame(hdr, bg=BG)
            yt.pack(pady=(6, 0))
            self.yt_btn = tk.Label(yt, text="▶  Race highlights", bg="#e62117", fg="white",
                                   font=("Segoe UI", 9, "bold"), padx=10, pady=3, cursor="hand2")
            self.yt_btn.pack(side="left", padx=4)
            self.yt_btn.bind("<Button-1>", lambda e: self._play_highlights())
            self.yt_btn.bind("<Enter>", lambda e: self.yt_btn.configure(bg="#ff3d33"))
            self.yt_btn.bind("<Leave>", lambda e: self.yt_btn.configure(bg="#e62117"))
            self.yt_tip = tk.Label(yt, text="plays on YouTube", bg=BG, fg=FG_DIM,
                                   font=("Segoe UI", 8))
            self.yt_tip.pack(side="left", padx=4)
        else:
            self.summary.configure(text="Results appear here after the race.")

        self.nb = ttk.Notebook(self.top)
        self.nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.msg = tk.Label(self.top, text="Loading…", bg=BG, fg=FG_DIM, font=("Segoe UI", 9))
        self.msg.pack(side="bottom", fill="x", pady=(0, 6))
        self.tabs = {}
        self.live_tree = None
        live = ticker.f1_live
        if live and (live["race"].get("season"), live["race"].get("round")) == \
                (race.get("season"), race.get("round")):
            fr = ttk.Frame(self.nb, padding=8)
            self.nb.add(fr, text=f"Live {live['which'].lower()}")
            self.live_info = tk.Label(fr, text="", bg=BG_PANEL, fg=LIVE,
                                      font=("Segoe UI", 10, "bold"), anchor="w")
            self.live_info.pack(fill="x", pady=(0, 6))
            f, self.live_tree = make_tree(fr, [
                ("pos", "Pos", 44), ("num", "No.", 44), ("name", "Driver", 190),
                ("team", "Team", 150), ("int", "Interval", 90), ("gap", "Gap to leader", 110),
                ("laps", "Laps", 50), ("pits", "Pit stops", 70), ("st", "Status", 60)], 20,
                sortable=False)
            f.pack(fill="both", expand=True)
            self.live_tree.tag_configure("p1", foreground=PODIUM[1])
            self.live_tree.tag_configure("p2", foreground=PODIUM[2])
            self.live_tree.tag_configure("p3", foreground=PODIUM[3])
            self.summary.configure(text="Race in progress: live standings in the first tab.")
            self._live_refresh()
        if results:
            fr, tree = self._tab("Race results", self.RESULT_COLS)
            self._fill_results(tree, results)
        else:
            self._fill_schedule()        # upcoming race: schedule first
        self.load()

    def _live_refresh(self):
        if not self.alive or self.live_tree is None:
            return
        live = self.ticker.f1_live
        if live:
            bits = ["LIVE"]
            if live.get("lap"):
                bits.append(f"Lap {live['lap']}")
            if live.get("track"):
                bits.append(live["track"].title())
            if live.get("source"):
                bits.append(f"Source: {live['source']}")
            if not live.get("rows"):
                bits.append(live.get("note") or "Waiting for live timing…")
            self.live_info.configure(text="   ·   ".join(bits))
            self._insert(self.live_tree, [
                (r["pos"], r.get("num", ""), r.get("name") or r["code"], r.get("team", ""),
                 r.get("interval", ""), r.get("gap", "") or ("" if r["pos"] != 1 else "—"),
                 r.get("laps", ""), r.get("pits", ""), r.get("status", ""))
                for r in live["rows"]])
        else:
            self.live_info.configure(text="The session has finished. Final results appear "
                                          "here shortly after the race.", fg=FG_DIM)
            return
        self.top.after(2500, self._live_refresh)

    def _tab(self, title, cols, height=20):
        fr = ttk.Frame(self.nb, padding=8)
        self.nb.add(fr, text=title)
        f, tree = make_tree(fr, cols, height)
        f.pack(fill="both", expand=True)
        tree.tag_configure("p1", foreground=PODIUM[1])
        tree.tag_configure("p2", foreground=PODIUM[2])
        tree.tag_configure("p3", foreground=PODIUM[3])
        self.tabs[title] = tree
        return fr, tree

    @staticmethod
    def _insert(tree, rows):
        tree.delete(*tree.get_children())
        for i, r in enumerate(rows):
            tags = ("odd",) if i % 2 else ()
            try:
                p = int(r[0])
                if p in PODIUM:
                    tags += (f"p{p}",)
            except (TypeError, ValueError):
                pass
            tree.insert("", "end", values=r, tags=tags)

    def _fill_results(self, tree, results, sprint=False):
        rows = []
        splits = f1_splits(results)
        for n, r in enumerate(results):
            d = r.get("Driver") or {}
            try:
                gain = int(r.get("grid") or 0) - int(r.get("position") or 0)
                gain = "" if int(r.get("grid") or 0) == 0 else (f"+{gain}" if gain > 0 else gain)
            except ValueError:
                gain = ""
            fl = r.get("FastestLap") or {}
            fl_txt = (fl.get("Time") or {}).get("time", "")
            if fl.get("rank") == "1":
                fl_txt += "  fastest"
            rows.append((r.get("position", ""), r.get("number", ""), f1_full_name(d),
                         (r.get("Constructor") or {}).get("name", ""), r.get("laps", ""),
                         f1_result_text(r) if f1_result_text(r) not in ("DNF",)
                         else f"DNF · {r.get('status', '')}",
                         "" if n == 0 else (splits[n] if splits[n].startswith("+") and
                                            "lap" not in splits[n].lower() else ""),
                         r.get("grid", ""), gain, r.get("points", ""), fl_txt))
        self._insert(tree, rows)

    def _fill_schedule(self):
        sessions = [("Practice 1", "FirstPractice"), ("Practice 2", "SecondPractice"),
                    ("Practice 3", "ThirdPractice"), ("Sprint qualifying", "SprintQualifying"),
                    ("Sprint qualifying", "SprintShootout"), ("Sprint", "Sprint"),
                    ("Qualifying", "Qualifying")]
        rows = []
        for label, key in sessions:
            sess = self.race.get(key)
            st = f1_start(sess)
            if st:
                rows.append((label, local_day(st.isoformat()), local_time(st.isoformat())))
        st = f1_start(self.race)
        if st:
            rows.append(("Race", local_day(st.isoformat()), local_time(st.isoformat())))
        if rows:
            fr, tree = self._tab("Weekend schedule", [("name", "Session", 200),
                                                      ("day", "Day", 140),
                                                      ("time", "Start (your time)", 140)], 8)
            fill_tree(tree, rows)

    def load(self):
        season, rnd = self.race.get("season"), self.race.get("round")

        def get(path, key):
            try:
                races = (fetch_json(f"{JOLPICA}/{path}").get("MRData") or {})
                return races
            except Exception:
                return {}

        def work():
            out = {}
            if self.race.get("Results"):
                out["quali"] = get(f"{season}/{rnd}/qualifying.json", "q")
                out["sprint"] = get(f"{season}/{rnd}/sprint.json", "s")
                base = f"{season}/{rnd}"
            else:
                base = "current"
            out["drivers"] = get(f"{base}/driverStandings.json", "d")
            out["teams"] = get(f"{base}/constructorStandings.json", "c")
            return out
        self.ticker.worker.run(work, self._on_data, lambda e: self.alive and self.msg.configure(
            text="Couldn't load the rest of the weekend's data.", fg=LIVE))

    def _on_data(self, d):
        if not self.alive:
            return
        sprint = (((d.get("sprint") or {}).get("RaceTable") or {}).get("Races") or [{}])[0]
        if sprint.get("SprintResults"):
            fr, tree = self._tab("Sprint", self.RESULT_COLS)
            self._fill_results(tree, sprint["SprintResults"], sprint=True)
        quali = (((d.get("quali") or {}).get("RaceTable") or {}).get("Races") or [{}])[0]
        if quali.get("QualifyingResults"):
            fr, tree = self._tab("Qualifying", [("pos", "Pos", 44), ("num", "No.", 44),
                                                ("name", "Driver", 200), ("team", "Team", 160),
                                                ("q1", "Q1", 100), ("q2", "Q2", 100),
                                                ("q3", "Q3", 100)])
            self._insert(tree, [(q.get("position", ""), q.get("number", ""),
                                 f1_full_name(q.get("Driver") or {}),
                                 (q.get("Constructor") or {}).get("name", ""), q.get("Q1", ""),
                                 q.get("Q2", ""), q.get("Q3", ""))
                                for q in quali["QualifyingResults"]])
        lists = ((d.get("drivers") or {}).get("StandingsTable") or {}).get("StandingsLists") or []
        if lists:
            fr, tree = self._tab("Driver standings", [("pos", "Pos", 44),
                                                      ("name", "Driver", 220),
                                                      ("team", "Team", 180), ("pts", "Points", 70),
                                                      ("wins", "Wins", 60)])
            mine = {f1_full_name((r.get("Driver") or {})) for r in
                    (self.race.get("Results") or [])[:3]}
            self._insert(tree, [(s.get("position", ""), f1_full_name(s.get("Driver") or {}),
                                 ", ".join(c.get("name", "") for c in s.get("Constructors") or []),
                                 s.get("points", ""), s.get("wins", ""))
                                for s in lists[0].get("DriverStandings") or []])
        lists = ((d.get("teams") or {}).get("StandingsTable") or {}).get("StandingsLists") or []
        if lists:
            fr, tree = self._tab("Constructor standings", [("pos", "Pos", 44),
                                                           ("name", "Team", 260),
                                                           ("pts", "Points", 70),
                                                           ("wins", "Wins", 60)])
            self._insert(tree, [(s.get("position", ""), (s.get("Constructor") or {}).get("name", ""),
                                 s.get("points", ""), s.get("wins", ""))
                                for s in lists[0].get("ConstructorStandings") or []])
        if self.race.get("Results"):
            self._fill_schedule()        # finished race: schedule goes last
        after = "after this race" if self.race.get("Results") else "so far this season"
        self.msg.configure(text=f"Championship standings are {after}.", fg=FG_DIM)

    def _play_highlights(self):
        btn = self.yt_btn
        if getattr(btn, "_busy", False):
            return
        btn._busy = True
        btn.configure(text="  Finding video…  ")
        loc = (self.race.get("Circuit") or {}).get("Location") or {}
        name = self.race.get("raceName", "")
        info = {"key": "f1:F1", "full": "Formula 1", "nick": "F1", "opp_full": name,
                "opp_words": [loc.get("locality", ""), loc.get("country", ""),
                              name.replace("Grand Prix", "").strip()],
                "start": f1_start(self.race), "league_channel": "FORMULA 1",
                "query": f"{self.race.get('season', '')} {name} race highlights"}
        cache = self.ticker.cfg.setdefault("yt_channels", {})

        def done(res):
            url, source = res
            btn._busy = False
            if self.alive:
                btn.configure(text="▶  Race highlights")
                self.yt_tip.configure(
                    text="video not posted yet — showing YouTube search" if source == "search"
                    else f"playing from {source}")
            save_config(self.ticker.cfg)
            webbrowser.open(url)
        self.ticker.worker.run(lambda: find_highlight_video(info, cache), done,
                               lambda e: done((highlights_search_url(info), "search")))

    def close(self):
        self.alive = False
        self.top.destroy()
        self.ticker.detail_windows.pop(self.key, None)


# ------------------------------------------------------------------ main ----
def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()
    app = Ticker(root)
    try:
        root.mainloop()
    finally:
        app.appbar_remove()   # always give the screen space back


if __name__ == "__main__":
    main()
