# Changelog

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
- Continuous integration: the 244-test suite (226 default, 18 live-network
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
