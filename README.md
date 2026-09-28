# RF Repeater Site Finder

Terrain-aware candidate shortlisting for portable radio repeater planning, developed with AI assistance to address a practical organisational capability gap.

The browser application and Python service compare candidate locations using terrain, access information and independent repeater-to-portable and portable-to-repeater link calculations. A native wrapper integrates the NTIA Irregular Terrain Model (ITM). Uncertain terrain or access evidence remains visible to the operator.

## Source map

- `apps/web`: browser interface.
- `services/api`: analysis jobs, saved results, authentication and analysis engine.
- `native/rf-core`: native ITM wrapper; upstream code fetched at a pinned revision.
- `packages/schemas`: interchange contracts and fixtures.
- `data/sample-region`: synthetic golden profile only.

## Local verification

Requires Python 3, a C++ compiler and Make. Install Python dependencies from `services/api/requirements.txt` into an isolated environment.

```sh
make rf-core-vendor rf-core-build rf-core-test
make test-schemas api-test mvp-test
```

The vendor script fetches NTIA ITM separately; preserve its upstream licence and notices. No terrain dataset, map tiles or incident results are distributed here. Runtime elevation, Landgate and OpenStreetMap services have their own terms and attribution requirements.

## Configuration and limits

The public snapshot contains no operational authentication tenant. Configure your own provider in `apps/web/config.js` and the `MVP_SUPABASE_URL` / `MVP_SUPABASE_PUBLISHABLE_KEY` environment settings. Authentication stays enabled by default. Host and gateway deployment runbooks are excluded.

Candidate scores are planning evidence, not assurance of coverage, legal access, frequency authorisation or operational safety. Field assessment remains necessary. The mobile directory is a scaffold, not a finished mobile application. No runtime AI capability is claimed.

See [publication boundaries](PUBLICATION.md).
