#!/usr/bin/env python3
"""
Harmonix Vault Report — Reads latest snapshot from SQLite and prints a summary.

Usage:
    python query_report.py           # Full report (all vaults)
    python query_report.py --json    # Output as JSON
    python query_report.py --vault hyperevm-khype-v1  # Single vault
"""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Resolve profile dir (priority order):
# 1. HARMONIX_PROFILE_DIR env var (explicit override)
# 2. Relative to this script: bin/ is inside the profile dir, so parent.parent
# 3. Fallback: ~/.hermes/profiles/harmonix-point
#
# In Hermes/Codex where Path.home() is virtualized, option 2 handles it automatically.
import os
_env_profile_dir = os.environ.get("HARMONIX_PROFILE_DIR")
if _env_profile_dir:
    PROFILE_DIR = Path(_env_profile_dir)
else:
    PROFILE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROFILE_DIR / "data" / "harmonix_points.db"


def get_conn():
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        print("Run collect_points.py first to populate data.")
        sys.exit(1)
    return sqlite3.connect(str(DB_PATH))


def fetch_latest(conn, vault_slug=None):
    cur = conn.cursor()

    # Latest snapshot
    cur.execute("SELECT id, collected_at, total_tvl, total_depositors, total_stake, total_stake_usd, total_assets FROM snapshots ORDER BY id DESC LIMIT 1")
    snap = cur.fetchone()
    if not snap:
        return None, []

    snap_id, collected_at, total_tvl, total_depositors, total_stake, total_stake_usd, total_assets = snap

    # Vault snapshots
    if vault_slug:
        cur.execute(
            "SELECT id, slug, name, vault_currency, network_chain, tvl_usd, apy_30d, price_per_share, risk_factor FROM vault_snapshots WHERE snapshot_id = ? AND slug = ?",
            (snap_id, vault_slug),
        )
    else:
        cur.execute(
            "SELECT id, slug, name, vault_currency, network_chain, tvl_usd, apy_30d, price_per_share, risk_factor FROM vault_snapshots WHERE snapshot_id = ? ORDER BY tvl_usd DESC",
            (snap_id,),
        )
    vaults = cur.fetchall()

    # Points per vault (only non-zero)
    vault_points = {}
    for vault_row in vaults:
        vsid = vault_row[0]
        cur.execute(
            "SELECT point_name, point_value FROM point_snapshots WHERE vault_snapshot_id = ? AND point_value > 0 ORDER BY point_value DESC",
            (vsid,),
        )
        pts = cur.fetchall()
        if pts:
            vault_points[vsid] = pts

    snapshot_meta = {
        "collected_at": collected_at,
        "total_tvl": total_tvl,
        "total_depositors": total_depositors,
        "total_stake": total_stake,
        "total_stake_usd": total_stake_usd,
        "total_assets": total_assets,
    }
    return snapshot_meta, vaults, vault_points


def format_number(n):
    if n is None:
        return "N/A"
    if n >= 1_000_000:
        return f"${n:,.0f}"
    return f"${n:,.2f}"


def format_report(meta, vaults, vault_points):
    lines = []

    # Header
    try:
        dt = datetime.fromisoformat(meta["collected_at"].replace("Z", "+00:00"))
        ts = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        ts = meta["collected_at"]

    lines.append(f"Harmonix Vaults — {ts}")
    lines.append("")
    lines.append(
        f"Total Assets: {format_number(meta['total_assets'])} | "
        f"Depositors: {meta['total_depositors']:,} | "
        f"HYPE Staked: {format_number(meta['total_stake_usd'])}"
    )

    for vault_row in vaults:
        vsid, slug, name, currency, chain, tvl_usd, apy_30d, pps, risk = vault_row
        lines.append("")
        lines.append(f"{name} ({currency} · {chain})")
        lines.append(
            f"  TVL: {format_number(tvl_usd)} | "
            f"APY 30D: {apy_30d:.2f}% | "
            f"Price/Share: {pps:.6f} | "
            f"Risk: {risk if risk else 0}"
        )
        pts = vault_points.get(vsid, [])
        if pts:
            pt_str = " · ".join(f"{name} {val:,.0f}" for name, val in pts)
            lines.append(f"  Points: {pt_str}")

    return "\n".join(lines)


def format_json(meta, vaults, vault_points):
    result = {
        "snapshot": meta,
        "vaults": [],
    }
    for vault_row in vaults:
        vsid, slug, name, currency, chain, tvl_usd, apy_30d, pps, risk = vault_row
        result["vaults"].append({
            "slug": slug,
            "name": name,
            "vault_currency": currency,
            "network_chain": chain,
            "tvl_usd": tvl_usd,
            "apy_30d": apy_30d,
            "price_per_share": pps,
            "risk_factor": risk,
            "points": [{"name": n, "value": v} for n, v in vault_points.get(vsid, [])],
        })
    return json.dumps(result, indent=2, ensure_ascii=False)


def main():
    args = sys.argv[1:]
    output_json = "--json" in args
    vault_slug = None
    if "--vault" in args:
        idx = args.index("--vault")
        if idx + 1 < len(args):
            vault_slug = args[idx + 1]

    conn = get_conn()
    result = fetch_latest(conn, vault_slug)
    conn.close()

    if result[0] is None:
        print("No data found. Run collect_points.py first.")
        sys.exit(1)

    meta, vaults, vault_points = result

    if not vaults:
        print(f"No vault found{' for slug: ' + vault_slug if vault_slug else ''}.")
        sys.exit(1)

    if output_json:
        print(format_json(meta, vaults, vault_points))
    else:
        print(format_report(meta, vaults, vault_points))


if __name__ == "__main__":
    main()
