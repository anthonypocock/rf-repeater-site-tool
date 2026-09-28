# Snapshot verification — 28 September 2026

- Secret scan of the exact tracked export: no findings (Gitleaks 8.30.1).
- Schema, job runner, analysis lifecycle, authentication and saved-result checks passed.
- Native NTIA ITM wrapper built and synthetic golden-profile check passed.
- MVP analysis checks passed.
- Upstream ITM is fetched at a pinned revision and excluded from this repository's tracked files. The local include-path patch was made portable across macOS and Linux.
- Live hosting, browser layout, field coverage and access suitability were not verified by this source publication.

Operational authentication configuration and runbooks are excluded. Authentication remains enabled; operators must supply their own configuration. No terrain or incident dataset is distributed.

## Second publication review

Reviewed tracked files and public branch/tag history again. Removed residual organisational labels and example location references. The original public snapshot was briefly accessible before this correction; rewriting the branch cannot guarantee removal of third-party copies or cached objects.
