# -*- coding: utf-8 -*-
"""Import an exact legacy SQLite snapshot supplied via LEGACY_IMPORT_B64.

The payload is zlib-compressed JSON encoded with base64 and stored only in
Railway environment variables. No participant data is committed to GitHub.
"""
import os, json, zlib, base64
import server

TABLES = ["settings","participants","players","rounds","lineups","lineup_players","events"]
DELETE_ORDER = ["lineup_players","lineups","events","participants","players","rounds","settings"]

def decode_payload():
    raw = os.environ.get("LEGACY_IMPORT_B64","").strip()
    if not raw:
        raise SystemExit("LEGACY_IMPORT_B64 is empty; refusing to import.")
    return json.loads(zlib.decompress(base64.b64decode(raw)).decode("utf-8"))

def import_snapshot():
    if not server.PG:
        raise SystemExit("This importer is intended for PostgreSQL only.")
    payload = decode_payload()
    for t in TABLES:
        if t not in payload or not isinstance(payload[t], list):
            raise ValueError(f"Missing/invalid table payload: {t}")

    conn = server.conn
    old_autocommit = conn.autocommit
    conn.autocommit = False
    cur = conn.cursor()
    try:
        for t in DELETE_ORDER:
            cur.execute(f"DELETE FROM {t}")

        for r in payload["settings"]:
            cur.execute("INSERT INTO settings(key,value) VALUES(%s,%s)", (r["key"],r["value"]))

        for r in payload["participants"]:
            cur.execute(
                "INSERT INTO participants(id,name,code_hash,code_hint,active,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (r["id"],r["name"],r["code_hash"],r.get("code_hint"),r["active"],r["created_at"])
            )

        for r in payload["players"]:
            cur.execute(
                "INSERT INTO players(id,name,group_no,active,created_at) VALUES(%s,%s,%s,%s,%s)",
                (r["id"],r["name"],r["group_no"],r["active"],r["created_at"])
            )

        for r in payload["rounds"]:
            cur.execute(
                "INSERT INTO rounds(id,number,name,status,lock_at,created_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (r["id"],r["number"],r["name"],r["status"],r.get("lock_at"),r["created_at"])
            )

        for r in payload["lineups"]:
            cur.execute(
                "INSERT INTO lineups(id,participant_id,round_id,captain_player_id,vice_player_id,chip,submitted_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (r["id"],r["participant_id"],r["round_id"],r["captain_player_id"],r["vice_player_id"],r.get("chip"),r["submitted_at"],r["updated_at"])
            )

        for r in payload["lineup_players"]:
            cur.execute(
                "INSERT INTO lineup_players(id,lineup_id,player_id,role,bench_order) VALUES(%s,%s,%s,%s,%s)",
                (r["id"],r["lineup_id"],r["player_id"],r["role"],r["bench_order"])
            )

        for r in payload["events"]:
            cur.execute(
                "INSERT INTO events(id,round_id,player_id,goals,wins,hattricks,attendance,best_player,yellow,red,no_shoes,own_goals,raw_points,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (r["id"],r["round_id"],r["player_id"],r["goals"],r["wins"],r["hattricks"],r["attendance"],r["best_player"],r["yellow"],r["red"],r["no_shoes"],r["own_goals"],r["raw_points"],r["updated_at"])
            )

        for t in ["participants","players","rounds","lineups","lineup_players","events"]:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{t}','id'), COALESCE((SELECT MAX(id) FROM {t}),1), true)"
            )

        conn.commit()
        counts={}
        for t in TABLES:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            counts[t]=cur.fetchone()[0]
        print("LEGACY IMPORT COMPLETE", counts)
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.autocommit = old_autocommit

if __name__ == "__main__":
    import_snapshot()
