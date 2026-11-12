# GitHub traffic archive

The GitHub Actions workflow **Archive GitHub traffic statistics** collects
repository traffic every hour into `stats/traffic.json`, after the repository
owner has configured the required secret.

## One-time setup

1. Open **GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens**.
2. Create a token scoped **only** to `shkabara2007/anenji-bms-monitor`
   with repository permission **Administration: Read-only**.
3. Open **this repository → Settings → Secrets and variables → Actions → New repository secret**.
4. Name the secret `GH_TRAFFIC_TOKEN` and paste the token there, not in the
   repository files or a chat.
5. Optionally trigger **Actions → Archive GitHub traffic statistics → Run workflow**.

The scheduled workflow runs hourly at minute 13 UTC, subject to GitHub
Actions scheduling delays. It requires repository Actions to be enabled and
the default `GITHUB_TOKEN` to have permission to commit changes.

On success, `stats/traffic.json` is automatically committed. It includes
14-day totals for views, unique visitors, clones and unique cloners; daily
history; top paths and referring sites; and historical daily snapshots.
GitHub Traffic's top paths and referrers cover a limited number of entries
and are not exhaustive.

Do not sum daily uniques as an all-time unique count. These are aggregated
anonymous metrics, not per-person activity. The repository is public, so
`stats/traffic.json` will also be public.

Once enabled, ChatGPT can retrieve the file from the linked GitHub repository
when asked for statistics, without requiring screenshots.
