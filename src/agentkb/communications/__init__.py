"""Communications store: imported messages, posts, and transcripts from human platforms."""

from agentkb.communications.parser import build_communications_index  # noqa: F401

# Register all communications sources on import
import agentkb.communications.sources.x  # noqa: F401
