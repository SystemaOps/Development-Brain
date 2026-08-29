"""Contract test framework.

Each ``*Contract`` class here is a suite of behavioral tests every adapter
implementation must pass.  Concrete test classes bind a specific adapter via a
fixture, so the same suite runs against the in-memory reference now and
against PostgreSQL/Neo4j/Weaviate adapters in later phases.
"""
