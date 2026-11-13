"""Player looks (avatar emoji + colour + frame) and the clan badge palette.

Everything is picked from curated presets — no uploads, no free text. Extra emojis
and frames unlock with the player's lifetime-credit rank, which never goes down.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ai_svc.spy_hunt import credits
from ai_svc.spy_hunt.db import get_conn
from ai_svc.spy_hunt.outfits import COLORS, EMOJIS
from ai_svc.spy_hunt.store import StoreError

FREE_EMOJIS = EMOJIS
# rank index -> emojis unlocked at that rank
RANK_EMOJIS: Dict[int, tuple] = {
    1: ("🐺", "🦝", "🐹", "🦔"),
    2: ("🕵️", "🥷", "🧙", "🦹"),
    3: ("🦅", "🐉", "🦈", "🐲"),
    4: ("🧠", "🔮", "💎", "🌋"),
    5: ("👑", "🦚", "🌟", "🏆"),
}
FRAMES = ("none", "leaf", "ribbon", "star", "gold", "crown")  # index == rank needed

CLAN_EMOJIS = ("🦊", "🐺", "🦉", "🐉", "🦁", "🐙", "🦅", "🐝", "🌵", "🚀", "⚡", "🔥",
               "🐻", "🐯", "🦈", "🐢", "🦄", "🐸", "🐼", "🦋", "🍄", "🌙", "⭐", "🎯",
               "🛡️", "⚓", "🎲", "🗝️", "🧭", "🦇")

_EMOJI_RANK: Dict[str, int] = {e: 0 for e in FREE_EMOJIS}
for _r, _es in RANK_EMOJIS.items():
    for _e in _es:
        _EMOJI_RANK.setdefault(_e, _r)


def _rank(conn, player_id: str) -> int:
    return credits.rank_for(credits.total(conn, player_id))["index"]


def get(player_id: str, conn=None) -> Optional[Dict[str, str]]:
    conn = conn or get_conn()
    row = conn.execute("SELECT emoji, color, frame FROM player_looks WHERE player_id=?",
                       (player_id,)).fetchone()
    return {"emoji": row["emoji"], "color": row["color"], "frame": row["frame"]} if row else None


def catalog(player_id: str) -> Dict[str, Any]:
    conn = get_conn()
    return {
        "emojis": [{"emoji": e, "rank": r} for e, r in _EMOJI_RANK.items()],
        "colors": list(COLORS),
        "frames": [{"key": k, "rank": i} for i, k in enumerate(FRAMES)],
        "rank": _rank(conn, player_id),
        "mine": get(player_id, conn),
    }


def _check(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise StoreError(400, "bad_look", "Pick an emoji, a colour and a frame.")
    emoji, color, frame = value.get("emoji"), value.get("color"), value.get("frame")
    if emoji not in _EMOJI_RANK or color not in COLORS or frame not in FRAMES:
        raise StoreError(400, "bad_look", "Pick one of the offered options.")
    return {"emoji": emoji, "color": color, "frame": frame}


def save(player_id: str, value: Any) -> Dict[str, Any]:
    look = _check(value)
    conn = get_conn()
    need = max(_EMOJI_RANK[look["emoji"]], FRAMES.index(look["frame"]))
    if _rank(conn, player_id) < need:
        raise StoreError(403, "look_locked", "Reach a higher rank to unlock that.")
    conn.execute(
        "INSERT INTO player_looks(player_id, emoji, color, frame, updated_at) VALUES(?,?,?,?,?)"
        " ON CONFLICT(player_id) DO UPDATE SET emoji=excluded.emoji, color=excluded.color,"
        " frame=excluded.frame, updated_at=excluded.updated_at",
        (player_id, look["emoji"], look["color"], look["frame"], int(time.time() * 1000)))
    conn.commit()
    _refresh_rooms(player_id, look)
    return catalog(player_id)


def _refresh_rooms(player_id: str, look: Dict[str, str]) -> None:
    """Wear the new look in rooms that aren't finished, each under its own room lock."""
    from ai_svc.spy_hunt import store
    rooms = get_conn().execute(
        "SELECT DISTINCT p.room_id FROM players p JOIN rooms r ON r.id=p.room_id"
        " WHERE p.player_id=? AND p.is_bot=0 AND r.status IN ('lobby', 'playing')",
        (player_id,)).fetchall()
    for (room_id,) in rooms:
        try:
            with store.tx(room_id) as conn:
                room = conn.execute("SELECT * FROM rooms WHERE id=?", (room_id,)).fetchone()
                seat = conn.execute("SELECT seat FROM players WHERE room_id=? AND player_id=? AND is_bot=0",
                                    (room_id, player_id)).fetchone()
                if room is None or seat is None or room["status"] == "finished":
                    continue
                conn.execute("UPDATE players SET avatar_emoji=?, avatar_color=?, avatar_frame=?"
                             " WHERE room_id=? AND seat=?",
                             (look["emoji"], look["color"], look["frame"], room_id, seat["seat"]))
                store._bump(conn, room_id)
                store._emit_player(conn, dict(room), seat["seat"], "player_updated")
        except Exception:  # a stale look must never fail the save itself
            import logging
            logging.getLogger(__name__).exception("look refresh failed for room %s", room_id)


def check_badge(value: Any) -> Dict[str, str]:
    if not isinstance(value, dict) or value.get("emoji") not in CLAN_EMOJIS \
            or value.get("color") not in COLORS:
        raise StoreError(400, "bad_badge", "Pick one of the offered badges.")
    return {"emoji": value["emoji"], "color": value["color"]}
