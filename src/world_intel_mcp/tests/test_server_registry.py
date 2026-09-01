"""Import-based tests for server.py's tool registry and dispatcher.

Every other test file reads server.py as *text* because importing it
opens a live ``Cache()``/``AOIStore()`` at the default on-disk path.
Here we import it for real, under a temp cache path
(``WORLD_INTEL_CACHE_DB`` is honored by ``Cache`` before the module-level
``cache = Cache()`` runs), which is what lets these tests verify the
registry structurally instead of by regex: the TOOLS/_dispatch parity
invariant, schema well-formedness, and the actual dispatch path for the
pure (no-network) tools.
"""

import importlib
import inspect
import os
import re
import tempfile
from pathlib import Path

import pytest

_TMP_CACHE = Path(tempfile.mkdtemp(prefix="wim-server-test-")) / "cache.db"


@pytest.fixture(scope="module")
def server():
    """Import server.py exactly once, cache pointed at a temp file."""
    prior = os.environ.get("WORLD_INTEL_CACHE_DB")
    os.environ["WORLD_INTEL_CACHE_DB"] = str(_TMP_CACHE)
    try:
        module = importlib.import_module("world_intel_mcp.server")
        yield module
    finally:
        if prior is None:
            os.environ.pop("WORLD_INTEL_CACHE_DB", None)
        else:
            os.environ["WORLD_INTEL_CACHE_DB"] = prior


def test_server_cache_landed_in_temp_path(server) -> None:
    """Guard for this file's own premise: if the env override stopped
    working, every test here would be silently exercising (and writing
    to) the developer's real cache."""
    assert Path(server.cache.db_path) == _TMP_CACHE


def test_tool_names_unique_and_conventional(server) -> None:
    names = [t.name for t in server.TOOLS]
    assert len(names) == len(set(names)), "duplicate tool name in TOOLS"
    non_conforming = [n for n in names if not n.startswith("intel_")]
    assert non_conforming == [], f"tools outside intel_* convention: {non_conforming}"


def test_every_tool_has_description_and_object_schema(server) -> None:
    for tool in server.TOOLS:
        assert tool.description and tool.description.strip(), tool.name
        assert isinstance(tool.inputSchema, dict), tool.name
        assert tool.inputSchema.get("type") == "object", tool.name


def test_tools_and_dispatch_are_in_one_to_one_parity(server) -> None:
    """The invariant ROADMAP.md carries ('TOOLS and _dispatch are
    aligned'), checked against the imported module rather than a text
    scan of the repo: every registered tool has a dispatch case and
    every dispatch case is a registered tool."""
    registered = {t.name for t in server.TOOLS}
    dispatch_src = inspect.getsource(server._dispatch)
    dispatched = set(re.findall(r'case "(intel_[a-z0-9_]+)"', dispatch_src))
    assert registered - dispatched == set(), "registered but never dispatched"
    assert dispatched - registered == set(), "dispatched but never registered"


def test_tool_count_matches_documented_surface(server) -> None:
    """122 = 121 intelligence tools + intel_status. If this fails after
    adding a tool, update README.md, ROADMAP.md, and this number in the
    same change: the repo's history shows doc counts drifting stale
    within weeks when nothing enforced them."""
    assert len(server.TOOLS) == 122


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_returns_error(server) -> None:
    result = await server._dispatch("intel_no_such_tool", {})
    assert result == {"error": "Unknown tool: intel_no_such_tool"}


@pytest.mark.asyncio
async def test_dispatch_reaches_real_aoi_store_round_trip(server) -> None:
    """Drive define -> list -> update -> delete through the real
    dispatcher and the module-level AOIStore (temp-backed): the tools
    exist end-to-end, not just as registry entries."""
    defined = await server._dispatch(
        "intel_aoi_define",
        {"name": "Registry Test", "lat": 40.44, "lon": -79.99, "radius_km": 25},
    )
    assert defined.get("aoi", {}).get("name") == "Registry Test"

    listed = await server._dispatch("intel_aoi_list", {})
    assert any(a["name"] == "Registry Test" for a in listed["aois"])

    updated = await server._dispatch(
        "intel_aoi_update", {"name": "Registry Test", "radius_km": 50}
    )
    assert updated.get("aoi", {}).get("radius_km") == 50.0

    deleted = await server._dispatch("intel_aoi_delete", {"name": "Registry Test"})
    assert deleted.get("deleted") == "Registry Test"


@pytest.mark.asyncio
async def test_dispatch_static_dataset_tool_works(server) -> None:
    """A pure static-config tool through the real dispatcher: no
    network, real data contract."""
    result = await server._dispatch("intel_military_bases", {})
    assert result.get("count", 0) >= 70
    assert any(
        b.get("name") == "Norfolk Naval Station" for b in result.get("bases", [])
    )
