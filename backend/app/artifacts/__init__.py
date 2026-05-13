"""Claude-Code-style artifact system.

When a user types a message in chat, the dispatcher classifies it into an
intent. If the intent matches an artifact kind (compare, draft, summary,
metrics, quotes), the appropriate generator runs and streams content into
a side-panel artifact instead of (or alongside) the usual chat reply.

Public surface:
    from app.artifacts.dispatcher import classify_intent
    from app.artifacts.generators import generate_artifact
"""
