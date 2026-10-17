# Security and downloaded source material

The public repository contains the research software and rights-filtered
portable database. Raw downloads belong in a local, ignored `data/` directory.
Do not commit `.env` files, API credentials, raw agency HTML, or confidential
immigration case records. Supply `GOVINFO_API_KEY` through the environment.

## Downloaded USCIS search-widget key

GitHub secret-scanning alert #1 identifies the three USCIS HTML pages containing a Google API key
in the agency's `uscis_design.apiKey_aao_pm_search` configuration. It was copied
from the public agency page; it was not created or used as a credential by this
project. Do not test, reuse, or attempt to revoke an agency-owned key.

The raw research directory has been removed from the public tree and its
rewritten branch history, and is ignored. `scripts/check_publication.py` checks the tracked boundary and
common credential patterns without displaying matched values. The portable
builder extracts readable text and omits script contents, and the Pages build
uses only approved portable assets.

On October 17, 2026, the owner authorized replacing the published history with
a clean root containing the approved project snapshot. No raw `data/` file or
flagged key is reachable through that rewritten branch. Old clones, forks,
cached commit pages, and GitHub's retained objects may still hold copies;
force-pushing does not guarantee their deletion or revoke any credential.
GitHub Support may be needed to remove cached views and retained objects.

The alert and all three paths were confirmed from the owner's October 17, 2026
screenshot. An owner should record the appropriate third-party-key disposition
in GitHub. Do not mark a real credential revoked unless its
issuer has actually revoked it. A public client-side key can be a real API key;
its appearance in public HTML alone does not establish that it is harmless.

For a new report, open a private vulnerability report on GitHub when available.
Include the affected path and commit, but do not paste the credential value.

After the rewrite, use a fresh clone instead of merging or force-pushing an old
local branch, which can reintroduce the removed history.
