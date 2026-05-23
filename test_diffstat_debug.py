import os

from bbmetrics_dc.client import BitbucketDCClient
from bbmetrics_dc.diffstat import get_commit_diffstat_totals

# Ajuste estes valores:
PROJECT = "KIOSK"
REPO_SLUG = "Kiosk"         # ou "kiosk" conforme o slug real no Bitbucket (normalmente é minúsculo)
COMMIT = "96ad9bedf244a92048540df42a15ee1dcd5c7fba"  # pegue do commits.csv (coluna commit_hash)

os.environ["BITBUCKET_BASE_URL"] = "https://git.rdisoftware.com:8443"

username = os.getenv("BITBUCKET_USERNAME")
password = os.getenv("BITBUCKET_PASSWORD")
if not username or not password:
    raise SystemExit("Set BITBUCKET_USERNAME and BITBUCKET_PASSWORD env vars first.")

client = BitbucketDCClient(base_url=os.environ["BITBUCKET_BASE_URL"], username=username, password=password)

outdir = "./out"
diff = get_commit_diffstat_totals(client, PROJECT, REPO_SLUG, COMMIT, debug_dir=outdir)
print(diff)
print("Look for diffstats_raw_*.json in:", outdir)