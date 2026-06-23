"""Unit tests for knowledge_service filtering.

Run: python -m unittest tests.test_knowledge_service -v
"""
import sys
import types
import unittest

# knowledge_service imports loguru; provide a lightweight fake for tests.
fake_loguru = types.ModuleType("loguru")
fake_loguru.logger = types.SimpleNamespace(
    info=lambda *a, **k: None,
    warning=lambda *a, **k: None,
    debug=lambda *a, **k: None,
    error=lambda *a, **k: None,
)
sys.modules["loguru"] = fake_loguru

from app.services.knowledge_service import KnowledgeBase, search_knowledge


class TestKnowledgeBase(unittest.TestCase):

    def setUp(self):
        self.kb = KnowledgeBase()

    def test_loads_chunks(self):
        self.assertGreater(len(self.kb.chunks), 0)
        sources = {c.source for c in self.kb.chunks}
        self.assertIn("phase1_user_guide.md", sources)

    def test_search_without_filter(self):
        results = self.kb.search("crear un bot", top_k=3)
        self.assertGreater(len(results), 0)
        # Without a filter we may get chunks from any source.
        sources = {c.source for c in results}
        self.assertGreaterEqual(len(sources), 1)

    def test_search_with_allowed_sources(self):
        results = self.kb.search(
            "crear un bot",
            top_k=3,
            allowed_sources=["phase1_user_guide.md"],
        )
        self.assertGreater(len(results), 0)
        for chunk in results:
            self.assertEqual(chunk.source, "phase1_user_guide.md")

    def test_search_with_unknown_source_returns_empty(self):
        results = self.kb.search(
            "crear un bot",
            top_k=3,
            allowed_sources=["nonexistent.md"],
        )
        self.assertEqual(results, [])

    def test_search_knowledge_passes_allowed_sources(self):
        results = search_knowledge(
            "crear un bot",
            top_k=3,
            allowed_sources=["phase1_user_guide.md"],
        )
        self.assertGreater(len(results), 0)
        for chunk in results:
            self.assertEqual(chunk.source, "phase1_user_guide.md")


if __name__ == "__main__":
    unittest.main()
