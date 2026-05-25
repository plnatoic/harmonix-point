#!/usr/bin/env python3
"""
Harmonix Points Collector — Fetch vault data from API and store in SQLite.

Usage:
    python collect_points.py              # Single run
    python collect_points.py --continuous  # Run every 15 minutes
    python collect_points.py --interval 30 # Custom interval (minutes)
"""

import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    import urllib.request
    import urllib.error

    class _RequestsShim:
        """Fallback when requests is not installed."""

        @staticmethod
        def get(url, timeout=30):
            req = urllib.request.Request(url)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    class R:
                        status_code = resp.status
                        text = resp.read().decode()

                        def json(self):
                            return json.loads(self.text)

                        def raise_for_status(self):
                            pass

                    return R()
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"HTTP {e.code}: {e.read().decode()}") from e

    requests = _RequestsShim()

BASE_URL = "https://api.harmonix.fi/api/v1"

# Resolve profile dir (priority order):
# 1. HARMONIX_PROFILE_DIR env var (explicit override)
# 2. Relative to this script: bin/ is inside the profile dir, so parent.parent
# 3. Fallback: ~/.hermes/profiles/harmonix-point
#
# In Hermes/Codex where Path.home() is virtualized, option 2 handles it automatically.
_env_profile_dir = os.environ.get("HARMONIX_PROFILE_DIR")
if _env_profile_dir:
    PROFILE_DIR = Path(_env_profile_dir)
else:
    PROFILE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROFILE_DIR / "data"
DB_PATH = DATA_DIR / "harmonix_points.db"
RAW_DIR = DATA_DIR / "raw"

SLUGS = [
    "hip3-usdc-vault",
    "hyperevm-khype-v1",
    "hype-delta-neutral-v1",
    "hyperevm-delta-neutral-hype-v3",
    "kelpdao-restaking-delta-neutral-vault",
]


def ensure_dirs():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def init_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            total_tvl       REAL,
            total_depositors INTEGER,
            total_stake     REAL,
            total_stake_usd REAL,
            total_assets    REAL
        );

        CREATE TABLE IF NOT EXISTS vault_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id     INTEGER REFERENCES snapshots(id),
            collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            slug            TEXT NOT NULL,
            name            TEXT,
            category        TEXT,
            network_chain   TEXT,
            vault_currency  TEXT,
            tvl             REAL,
            tvl_usd         REAL,
            price_per_share REAL,
            apy_1y          REAL,
            apy_7d          REAL,
            apy_15d         REAL,
            apy_30d         REAL,
            apy_45d         REAL,
            risk_factor     REAL,
            tags            TEXT,
            contract_address TEXT,
            strategy_name   TEXT,
            rewards_count   INTEGER DEFAULT 0,
            max_drawdown    REAL
        );

        CREATE TABLE IF NOT EXISTS point_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_snapshot_id INTEGER REFERENCES vault_snapshots(id),
            collected_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
            vault_slug      TEXT NOT NULL,
            point_name      TEXT NOT NULL,
            point_value     REAL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_time ON snapshots(collected_at);
        CREATE INDEX IF NOT EXISTS idx_vault_slug_time ON vault_snapshots(slug, collected_at);
        CREATE INDEX IF NOT EXISTS idx_point_slug_name_time ON point_snapshots(vault_slug, point_name, collected_at);
    """)
    conn.commit()
    return conn


def fetch_statistics():
    url = f"{BASE_URL}/statistics/"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_vault(slug):
    url = f"{BASE_URL}/vaults/{slug}"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_staking():
    url = f"{BASE_URL}/stakings/get-all-total-staked/"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def save_raw(data, prefix="snapshot"):
    now = datetime.now(timezone.utc)
    date_dir = RAW_DIR / now.strftime("%Y-%m-%d")
    date_dir.mkdir(parents=True, exist_ok=True)
    filepath = date_dir / f"{prefix}_{now.strftime('%H%M%S')}.json"
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return filepath


def collect(conn):
    now = datetime.now(timezone.utc).isoformat()
    print(f"[{now}] Collecting Harmonix data...")

    # 1. Fetch statistics
    stats = fetch_statistics()
    staking = fetch_staking()
    save_raw({"statistics": stats, "staking": staking}, prefix="stats")

    # 2. Insert snapshot
    total_tvl = stats.get("tvl_in_all_vaults", 0)
    total_stake_usd = staking.get("total_stake_usd", 0)
    total_assets = total_tvl + total_stake_usd
    cur = conn.execute(
        "INSERT INTO snapshots (collected_at, total_tvl, total_depositors, total_stake, total_stake_usd, total_assets) VALUES (?, ?, ?, ?, ?, ?)",
        (
            now,
            total_tvl,
            stats.get("total_depositors"),
            staking.get("total_stake"),
            total_stake_usd,
            total_assets,
        ),
    )
    snapshot_id = cur.lastrowid

    # 3. Fetch each vault detail
    all_vaults = {}
    for slug in SLUGS:
        try:
            vault = fetch_vault(slug)
            all_vaults[slug] = vault
        except Exception as e:
            print(f"  ⚠ Failed to fetch {slug}: {e}")
            continue

    save_raw(all_vaults, prefix="vaults")

    # 4. Build price_per_share lookup from statistics (vault detail returns 0.0)
    stats_pps = {}
    for v in stats.get("vaults", []):
        stats_pps[v.get("slug")] = v.get("price_per_share", 0.0)

    # 5. Insert vault snapshots + points
    for slug, vault in all_vaults.items():
        cur = conn.execute(
            """INSERT INTO vault_snapshots
            (snapshot_id, collected_at, slug, name, category, network_chain, vault_currency,
             tvl, tvl_usd, price_per_share, apy_1y, apy_7d, apy_15d, apy_30d, apy_45d,
             risk_factor, tags, contract_address, strategy_name, rewards_count, max_drawdown)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id,
                now,
                slug,
                vault.get("name"),
                vault.get("category"),
                vault.get("network_chain"),
                vault.get("vault_currency"),
                vault.get("tvl"),
                vault.get("tvl_usd"),
                stats_pps.get(slug, vault.get("price_per_share", 0.0)),
                vault.get("apy"),
                vault.get("apy_7d"),
                vault.get("apy_15d"),
                vault.get("apy_30d"),
                vault.get("apy_45d"),
                vault.get("risk_factor"),
                json.dumps(vault.get("tags", [])),
                vault.get("contract_address"),
                vault.get("strategy_name"),
                len(vault.get("rewards", [])),
                vault.get("max_drawdown"),
            ),
        )
        vault_snapshot_id = cur.lastrowid

        for point in vault.get("points", []):
            conn.execute(
                """INSERT INTO point_snapshots
                (vault_snapshot_id, collected_at, vault_slug, point_name, point_value)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    vault_snapshot_id,
                    now,
                    slug,
                    point.get("name"),
                    point.get("point"),
                ),
            )

    conn.commit()

    # 5. Summary
    total_vaults = len(all_vaults)
    total_points = sum(len(v.get("points", [])) for v in all_vaults.values())
    print(f"  ✅ Snapshot #{snapshot_id}: {total_vaults} vaults, {total_points} points")
    print(f"  💰 Total TVL: ${stats.get('tvl_in_all_vaults', 0):,.2f}")
    print(f"  👥 Depositors: {stats.get('total_depositors', 0):,}")
    return snapshot_id


def main():
    ensure_dirs()
    conn = init_db()

    # Parse args
    continuous = "--continuous" in sys.argv
    interval = 15
    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])

    if continuous:
        print(f"🔄 Running continuously every {interval} minutes. Ctrl+C to stop.")
        while True:
            try:
                collect(conn)
            except Exception as e:
                print(f"  ❌ Error: {e}")
            print(f"  ⏳ Next run in {interval} minutes...")
            time.sleep(interval * 60)
    else:
        try:
            collect(conn)
        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)
        finally:
            conn.close()


if __name__ == "__main__":
    main()
