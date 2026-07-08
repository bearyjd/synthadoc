# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Paul Chen / axoviq.com
"""Baseline smoke tests: the shipped demo wikis still work.

These exercise the demo_wiki fixture end to end via the real HTTP app, so an
agent reproducing a bug report against a demo wiki has a working template.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch


DEMO_NAMES = ["ai-research", "history-of-computing"]


@pytest.mark.parametrize("demo_name", DEMO_NAMES)
def test_query_endpoint_succeeds_on_demo_wiki(demo_wiki, demo_name):
    from synthadoc.integration.http_server import create_app
    from synthadoc.agents.query_agent import QueryResult

    wiki = demo_wiki(demo_name)
    app = create_app(wiki_root=wiki)
    mock = QueryResult(question="q", answer="answer", citations=["p1"])
    with patch(
        "synthadoc.core.orchestrator.Orchestrator.query",
        new=AsyncMock(return_value=mock),
    ):
        with TestClient(app) as client:
            resp = client.post("/query", json={"question": "What is this wiki about?"})
    assert resp.status_code == 200
    assert resp.json()["answer"] == "answer"


@pytest.mark.parametrize("demo_name", DEMO_NAMES)
def test_lint_report_succeeds_on_demo_wiki(demo_wiki, demo_name):
    from synthadoc.integration.http_server import create_app

    wiki = demo_wiki(demo_name)
    with TestClient(create_app(wiki_root=wiki)) as client:
        resp = client.get("/lint/report")
    assert resp.status_code == 200
    data = resp.json()
    assert "contradictions" in data
    assert "orphans" in data
