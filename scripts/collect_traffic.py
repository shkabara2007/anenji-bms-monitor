#!/usr/bin/env python3
"""Archive aggregate GitHub traffic without collecting personal visitor data."""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPOSITORY = os.environ.get("GITHUB_REPOSITORY", "shkabara2007/anenji-bms-monitor")
TOKEN = os.environ.get("GH_TRAFFIC_TOKEN", "").strip()
OUT = Path("stats/traffic.json")


def get(path: str):
    request = Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "User-Agent": "anenji-bms-monitor-traffic-collector",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(
            f"GitHub traffic request {path} failed (HTTP {exc.code}). "
            "Check GH_TRAFFIC_TOKEN: repository selection and Administration: read."
        ) from None


def main():
    if not TOKEN:
        print("GH_TRAFFIC_TOKEN is not configured; collection skipped.")
        return
    if not REPOSITORY or "/" not in REPOSITORY:
        raise RuntimeError("GITHUB_REPOSITORY must be OWNER/REPO")

    views = get("traffic/views?per=day")
    clones = get("traffic/clones?per=day")
    paths = get("traffic/popular/paths")
    referrers = get("traffic/popular/referrers")
    repo = get("")

    data = {}
    if OUT.exists():
        data = json.loads(OUT.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise RuntimeError("stats/traffic.json is not a JSON object")

    daily = data.get("daily", {})
    for item in views.get("views", []):
        date = item["timestamp"][:10]
        daily.setdefault(date, {}).update(
            views=item["count"], unique_visitors=item["uniques"]
        )
    for item in clones.get("clones", []):
        date = item["timestamp"][:10]
        daily.setdefault(date, {}).update(
            clones=item["count"], unique_cloners=item["uniques"]
        )

    now = dt.datetime.now(dt.timezone.utc)
    day = now.date().isoformat()
    rolling = {
        "views": views.get("count"),
        "unique_visitors": views.get("uniques"),
        "clones": clones.get("count"),
        "unique_cloners": clones.get("uniques"),
    }
    snapshots = data.get("rolling_14_day_snapshots", {})
    snapshots[day] = rolling
    popular_snapshots = data.get("popular_pages_snapshots", {})
    popular_snapshots[day] = paths
    referrer_snapshots = data.get("referrer_snapshots", {})
    referrer_snapshots[day] = referrers

    output = {
        "repository": REPOSITORY,
        "updated_at_utc": now.isoformat(timespec="seconds"),
        "rolling_14_days": rolling,
        "repository_totals": {
            "stars": repo.get("stargazers_count"),
            "forks": repo.get("forks_count"),
            "watchers": repo.get("subscribers_count"),
        },
        "popular_pages_last_14_days": paths,
        "referring_sites_last_14_days": referrers,
        "daily": dict(sorted(daily.items())),
        "rolling_14_day_snapshots": dict(sorted(snapshots.items())),
        "popular_pages_snapshots": dict(sorted(popular_snapshots.items())),
        "referrer_snapshots": dict(sorted(referrer_snapshots.items())),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Collected {REPOSITORY}: views={rolling['views']}, clones={rolling['clones']}")


if __name__ == "__main__":
    main()
