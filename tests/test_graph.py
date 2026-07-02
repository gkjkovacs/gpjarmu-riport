"""Smoke test: assemble the full LangGraph graph without running it."""
from __future__ import annotations

from gpjarmu_riport.config import LLMProvider, Settings
from gpjarmu_riport.graph import build_graph
from gpjarmu_riport.state.db import StateDB


def test_graph_assembles() -> None:
    s = Settings(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
    )
    db = StateDB(s.state_db_path)
    graph = build_graph(s, db)
    assert graph is not None


def test_graph_nodes_are_callable() -> None:
    s = Settings(
        llm_provider=LLMProvider.OPENAI,
        llm_api_key="test-key",
    )
    db = StateDB(s.state_db_path)
    graph = build_graph(s, db)
    nodes = graph.nodes
    expected = {
        "discover_issues", "fetch_content", "classify",
        "dedupe", "expand", "render_email",
    }
    assert expected.issubset(set(nodes.keys()))
