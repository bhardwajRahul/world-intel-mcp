# Changelog

## 0.5.0 - 2026-09-01

Geofences in any shape, four new hazard domains, precise entity
matching, and the last coverage zeros gone.

### Added
- **Polygon AOIs** — `intel_aoi_define_polygon` (+1 tool): a named area
  bounded by 3-64 [lat, lon] vertices, for shapes a radius cannot
  express (a border region, a strait, an EEZ). Every intel_aoi_* tool
  scopes to the exact polygon: an event inside the bounding circle but
  outside the polygon is excluded. Polygons may cross the antimeridian.
  Point infrastructure matches the exact shape; line features
  (pipelines, cables) match the bounding circle, disclosed in
  `data_gaps` rather than silently approximated.
- **Corridor AOIs** — `intel_aoi_define_corridor` (+1 tool): a route of
  waypoints plus a width in km (a shipping lane, a supply road, a cable
  run), built on the great-circle segment distance from 0.4.0.
  Distances in results are measured to the route, not to a center.
  Existing AOI databases migrate in place; old rows read as circles.
- **Four hazard/space domains** (+4 tools = 128), each verified against
  its live API before mocking: `intel_weather_alerts` (NWS CAP, US
  only, honest null coordinates for zone-based alerts),
  `intel_launch_schedule` (Launch Library 2, hour-long cache for the
  free tier), `intel_volcano_activity` (Smithsonian GVP weekly
  report), `intel_cyclones` (NHC active storms - Atlantic/E-C Pacific
  basins only; zero storms is a quiet tropics, not an outage).
- CLI and collector test waves: `cli.py` 0% -> 92% (76 tests driving
  all 52 reachable commands through CliRunner), `collector.py`
  20% -> 97% (run loop, daemon cycle, source-filter resolution). The
  last of the coverage zeros from the 0.4.0 audit.

### Fixed
- Entity extraction no longer substring-matches: "usa" inside
  "thousand" tagged the United States, "hamas" inside "Bahamas",
  "trump" inside "trumpet", "meta" inside "metadata". Countries,
  leaders, organizations, and companies now use the same precompiled
  word-boundary alternation the APT-group matcher always had (with a
  plural allowance for country demonyms). Verified faster per call on
  headline-size inputs.
- Event classification keywords are boundary-anchored stems:
  "launched" still classifies space, but "strike" inside "airstrike"
  no longer adds a social-unrest category and severity bump, "ied"
  inside "denied" no longer fires, "coup" inside "couple" no longer
  fires. A benign sentence that previously triggered four categories
  at severity 7 now classifies as nothing.

### Known issues (pinned by tests, fix planned)
- ~30 CLI commands render an upstream `{"error": ...}` as a
  healthy-looking empty state ("0 earthquakes" on an outage), and
  lowercase bracketed values in Rich output are swallowed as markup
  (the `intel report` fallback hint prints a pip command missing its
  `[pdf]` extra). Both are documented by deliberately-pinning tests
  in `test_cli.py` and tracked in ROADMAP Phase 24.5.

## 0.4.0 - 2026-09-01

Geofences that survive the dateline, notice change, a test suite that
reaches the layers the old one never imported, and outages that say so
instead of reading as good news.

### Added
- `intel_aoi_changes` (+1 tool): geofence change detection — what
  entered or left a user-defined AOI since the last sweep, per domain
  (earthquakes, military flights, ACLED conflict events, wildfire
  clusters, news mentions), built on the same scoped gather as
  `intel_aoi_brief` so the two tools can never disagree about what is
  inside the fence. The first sweep is an explicit `baseline`; a
  domain whose fetch failed goes to `data_gaps`, is excluded from the
  diff (a failed fetch must never read as "everything left the
  area"), and keeps its last real observation for the next successful
  sweep. Sampled aviation is excluded by design: diffing a 1-in-10
  global sample would manufacture fake enter/leave events every run.
- `intel_aoi_update` (+1 tool = 122): rename and/or re-center/resize
  an AOI in place with define-grade validation and collision checks.
  A rename migrates the AOI's change-detection snapshot; a geometry
  change drops it, because the old baseline described a different
  piece of the planet.
- `SECURITY.md`: explicit threat model (prompted by the external
  report in issue #21) — what the trust boundaries are, what
  hardening exists inside them (parameterized SQL throughout, no
  shell/eval/exec, server-generated report paths), and what is out of
  scope for a single-user local OSINT tool.
- Test waves for the previously unexecuted layers: the `analysis/`
  NLP modules (classifier, entities, convergence, spikes, clustering,
  signals, focal points, surge, and more) and the low-coverage
  `sources/` modules (intelligence, cyber, climate, displacement,
  fleet, prediction, service_status, maritime, military parsing) had
  0-30% statement coverage; measured overall coverage was 59% before
  this release despite a green 309-test suite. At release: 597
  non-smoke tests, 81% statement coverage.
- CI coverage ratchet: `--cov-fail-under=80` on the test job
  (measured 81% on 2026-09-01; floor set one point under for platform
  variance). The floor only moves up.

### Fixed
- Antimeridian AOIs: the bounding box derived from an AOI's radius was
  clamped at lon ±180, so a Bering Strait or Fiji geofence silently
  lost everything on the far side of the dateline in the OpenSky
  military-flight path and could report a false "no FIRMS coverage"
  wildfire gap. Circles crossing the dateline now produce two boxes;
  military fetches run per box and merge (icao24 dedup); a one-box
  failure is reported as `partial coverage` in `data_gaps` instead of
  passing half-coverage off as full.
- Pipelines and undersea cables are matched as line features:
  great-circle segment distance (cross-track with endpoint clamping)
  replaces endpoint-only / landing-point-only proximity, so a
  pipeline or cable whose midspan passes through the AOI is detected
  even when its endpoints are hundreds of km away.
- `intel_world_brief` top stories always reported `article_count: 0`:
  the brief read `article_count` from news clusters, but
  `fetch_news_clusters` emits the member count as `size` (the
  silent-zero class again; found by the new analysis-layer tests).
  Reads `size` now, with `article_count` as fallback, plus a
  regression test in the real emitted shape.
- `intel_fleet_report` per-waterway warning counts were always 0: the
  report read `warning_count` but `fetch_vessel_snapshot` emits
  `naval_warnings` (same silent-zero class, also found by the new
  tests). Reads `naval_warnings` now, with `warning_count` fallback,
  plus a regression test in the real emitted shape.
- Cache database files are created with owner-only permissions
  (0600); the `-wal`/`-shm` sidecars inherit the mode (issue #21).
- `__version__` no longer drifts from `pyproject.toml` (it had been
  stuck at 0.1.0 since the first release): it now derives from the
  installed package metadata at runtime.
- A UNHCR outage no longer reads as zero refugees worldwide:
  `intel_displacement_summary`'s failure shape carries `error`,
  `degraded`, and `reason: unhcr_fetch_failed` instead of bare zeroed
  totals (#22).
- Climate zones whose fetch failed are named in `unavailable_zones`
  (with `degraded: true`) instead of silently vanishing; a full
  Open-Meteo outage is an `error` with a reason, and an invalid zone
  filter now says so and lists the valid keys (#23).
- "Resolved: Major outage" post-mortems no longer count as active
  critical incidents (resolution status outranks incident keywords),
  and a provider whose status feed is unreachable is named in
  `unavailable_providers` instead of masquerading as healthy with no
  incidents (#24).

## 0.3.0 - 2026-08-16

Briefs that show their work, and areas you define yourself.

### Added
- User-defined areas of interest (AOIs/geofences): `intel_aoi_define`,
  `intel_aoi_list`, `intel_aoi_delete`, `intel_aoi_brief`, and
  `intel_aoi_escalation` (+5 = 119 tools). Before this, only
  `intel_signal_convergence` accepted a real point-plus-radius,
  `intel_military_flights` took a bbox, and hotspot escalation scoring was
  restricted to the 22 hardcoded `INTEL_HOTSPOTS`. `intel_aoi_define`
  persists a named point-radius area (validated: lat -90..90, lon
  -180..180, radius_km 1..2000) in a dedicated `aois` table inside the
  existing SQLite cache database, rejecting a duplicate (case-insensitive)
  name by echoing the existing definition back instead of overwriting it.
  `intel_aoi_brief` composes a cited view of earthquakes, military flights
  (bbox derived from the radius), wildfires (region-mapped, since NASA
  FIRMS has no point+radius query), ACLED conflict events, sampled
  aviation traffic, nearby static infrastructure (bases, ports, pipelines,
  nuclear facilities, undersea cables, datacenters, spaceports) with
  distances in km, and news headline mentions of the AOI name, all
  filtered to the AOI's radius, with `data_gaps` naming every domain that
  couldn't be geographically scoped. `intel_aoi_escalation` reuses the
  existing `score_hotspot` scoring engine unmodified, scoped to the AOI's
  own radius rather than the fixed 2-degree window used for the 22
  built-in hotspots (#16).
- Situation briefs now cite their sources. `fetch_situation_brief` builds a
  numbered `sources` list while walking the overview data: domain, a short
  description or headline, a URL when the upstream item carries one, and a
  timestamp when available, covering every metric that contributes to the
  brief. The Ollama prompt is instructed to cite claims inline as `[n]`
  using only that list; the structured fallback brief cites mechanically,
  since it is assembled per-metric. The response gains `sources` and
  `cited`: `cited` is true only when the returned text actually contains a
  `[n]` matching a real source number, so a brief where the model ignored
  the citation instruction (or invented an out-of-range number) is
  distinguishable from one that genuinely cited its sources. A metric with
  no traceable upstream item is reported without a citation rather than
  pointing at something that isn't really there (#15).
- `intel_daily_digest`: a cited markdown morning brief composing top
  current events by domain, recent headlines, and, when the optional
  vector store is installed, recent activity trends and a 24-hour
  timeline. Every listed item carries a source reference. When the vector
  store isn't available, the Trends and Timeline sections say so via
  `data_gaps` instead of rendering as an empty, falsely-quiet section
  (#15).
- `intel_situation_brief` (+1 = 120 tools). The cited situation brief
  (#15) was previously reachable only through the dashboard's SSE
  overview; MCP clients, the primary consumer this server exists for,
  couldn't call it at all. The new tool gathers a bounded server-side
  overview (earthquakes, military flights, ACLED conflict events,
  wildfires, cyber threats, disease outbreaks, news, space weather,
  strategic posture, and the alert digest, not the dashboard's full
  47-source fan-out), then delegates to the existing, unmodified
  `fetch_situation_brief` for the AI-generated brief or its
  mechanically-cited fallback when Ollama is unreachable (#18).

### Fixed
- `_extract_metrics` (situation brief) read the earthquake event list under
  the key `events`, but `fetch_earthquakes` returns it under `earthquakes`,
  so the lookup always missed and `max_magnitude` was silently 0 in every
  brief ever generated. Found while wiring earthquake citations off the
  same field.
- Test counts in the docs lagged the 0.2.0 regression tests (claimed 244
  total when 0.2.0 itself shipped 256). Corrected to the live count.
- `fetch_gdelt_search` returned a clean zero-article payload when the
  GDELT API call failed, byte-identical to a genuine zero-hit search:
  same class as the ACLED defect fixed in 0.2.0 (#3). Observed live as a
  429: GDELT asks for one request per 5 seconds. Failure paths now carry
  `error`, `degraded`, and `reason` keys, keeping `articles`/`count` in
  their normal empty shape; `intel_aoi_brief`'s news domain now surfaces
  the failure as a `data_gap` instead of reading as "no news mentions"
  (#17).

## 0.2.0 - 2026-08-16

The honesty release. A full review of the data paths found five ways the
server could present missing or stale data as fresh and real. All five are
fixed, each with a regression test that fails against the old code.

### Fixed
- ACLED-backed tools returned a clean zero-event payload when the API call
  failed, indistinguishable from genuine peace. Failure paths now carry
  `error`, `degraded`, and `reason` keys, and the eight downstream
  conflict/instability tools report `data_gaps` (#3).
- The documented `_stale=True` marker on cached fallback responses never
  actually existed. It does now, along with `_stale_age_seconds`; non-dict
  stale serves are counted in `CircuitBreaker.status()` (#4).
- `intel_gas_prices` restamped days-old cached prices with a fresh
  `fetched_at`. The timestamp now reflects the cached row's real age, and
  the fallback branch is reachable on real outages, which it previously
  was not (#5).
- `intel_hotspot_escalation` hardcoded its news and convergence components
  to zero for every hotspot, so an active war zone could score the lowest
  severity tier. Unmeasured components now report `null` and the score
  renormalizes over what was actually measured. The tool description no
  longer claims signals it cannot compute (#6).
- The circuit breaker stopped enforcing backoff after its first cooldown
  cycle: a failed half-open probe never re-timestamped the trip. Confirmed
  by repro, then fixed (#7).

### Added
- Continuous integration: the test suite (238 passing at this release, 18 live-network
  smoke tests deselected) now runs on every push and pull request, Python
  3.11 and 3.12 (#11).
- CONTRIBUTING.md, bug report and feature request templates (#12).
- This changelog (#14).

### Changed
- The collector launchd plist ships as a template; `collector-daemon.sh`
  resolves the repository root at runtime instead of hardcoding the
  maintainer's machine paths, and gained a `render` subcommand (#8).
- The situation brief's Ollama default is `localhost`, matching the rest
  of the codebase; `OLLAMA_API_URL` and `OLLAMA_MODEL` are documented (#9).
- README counts corrected against live code, all of them undercounts:
  226 passing tests (was "186"), 15 central banks (was "8"), 119 RSS feeds
  (was "80+"), 47 SSE sources (was "35+") (#10).
- `requirements.txt` removed; `pyproject.toml` is the single source of
  dependency truth (#13).

### Response-shape notes for MCP clients
All changes are additive (new keys only), with one exception: inside
`intel_hotspot_escalation`, each hotspot's `components` dict now reports
`social_unrest` and `convergence` as separate entries instead of the
combined `social_convergence`. Top-level shapes are unchanged.

## 0.1.0 - 2026-06-04

Everything before versioning began: 113 tools across 30+ domains built in
eighteen phases, from market data and SEC filings through conflict
tracking, military flights, climate, cyber, news, vector search over
accumulated intelligence, and a live Leaflet dashboard with SSE streaming.
The phase-by-phase history lives in ROADMAP.md.
