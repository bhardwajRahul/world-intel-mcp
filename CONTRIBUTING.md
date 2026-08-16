# Contributing

Thanks for taking a look at world-intel-mcp. This is a small project; the bar
is "does it work and does it fit the existing patterns," not process.

## Dev setup

```bash
git clone https://github.com/marc-shade/world-intel-mcp.git
cd world-intel-mcp
pip install -e ".[dev]"
```

`[dev]` pulls in `pytest`, `pytest-asyncio`, `pytest-cov`, and `respx`. If
you're touching the dashboard or the PDF report, also grab
`.[dashboard]` or `.[pdf]`.

## Running tests

```bash
pytest                          # full suite, live-network smoke tests deselected
pytest --cov=world_intel_mcp    # with coverage
pytest src/world_intel_mcp/tests/test_forex.py -v   # single module
pytest -m smoke                 # the live-network tests, opt-in only
```

Tests mock HTTP with `respx`, so nothing in the default run touches the
network. Fixtures in `conftest.py` (`cache`, `fetcher`) give you a clean
SQLite tmp-path cache and a fetcher with a fresh circuit breaker per test.

## Adding a new data source

This is the most common kind of PR, so here's the full recipe:

1. Create `sources/your_source.py` with:
   ```python
   async def fetch_your_data(fetcher: Fetcher, **kwargs) -> dict:
       ...
   ```
2. Fetch through `fetcher.get_json(url, source="your-source", cache_key=..., cache_ttl=300)`
   (or `get_text`/`get_xml`). Never construct your own `httpx` client: this
   is what gives you caching, retries, circuit breaking, and rate limiting
   for free.
3. Wire it into `server.py`: add a `Tool(...)` entry to `TOOLS` and a
   matching `case` in `_dispatch()` (inline-import the source module there,
   following the existing cases).
4. Write a test with `respx` mocking the HTTP call. `tests/test_forex.py`
   is a clean example of the pattern (success, empty response, error,
   cache-hit cases).
5. Optional but appreciated: add the source to `dashboard/app.py`'s SSE
   `source_defs` and to `cli.py` as a Click command, so it shows up in the
   live dashboard and the CLI, not just the MCP tool list.
6. If your tool count or feed count changes anything documented in
   `README.md` (the domain table, the tools reference, the architecture
   totals), update those numbers in the same PR. Stale counts are exactly
   what got filed as bugs before.

## Before opening a PR

- `pytest` passes locally (the CI matrix runs 3.11 and 3.12; if you have
  only one installed, that's fine, CI will catch the other).
- New source functions have a test.
- No new hardcoded personal paths, hostnames, or machine-specific defaults
  (see `sources/*.py` for the pattern: everything configurable comes from
  an env var with a sane public default).
- Keep the PR scoped to one thing. Bundling an unrelated formatting pass
  with a feature change makes it hard to review either one.

There's no linter configured in this repo on purpose. Don't add one as a
drive-by in an unrelated PR; that's its own decision.

## Dependencies

`pyproject.toml` is the single source of dependency truth. There is no
`requirements.txt`; don't add one back as a "quick pin" without also
wiring it into CI, or it will drift again.
