"""Prompt resolution for agentkb."""

from importlib import resources
from pathlib import Path


def resolve_prompt(name: str = "consolidate_chats") -> str:
    """Resolve a prompt by name.

    Resolution order:
    1. If name is a file path that exists, read it directly
    2. ~/.agentkb/prompts/{name}.md (user custom/override)
    3. Shipped default in this package

    Returns the prompt text.
    Raises FileNotFoundError if no prompt is found.
    """
    # 1. Direct file path
    path = Path(name)
    if path.suffix and path.expanduser().exists():
        return path.expanduser().read_text()

    # 2. User override
    user_path = Path.home() / ".agentkb" / "prompts" / f"{name}.md"
    if user_path.exists():
        return user_path.read_text()

    # 3. Shipped default
    try:
        return resources.files(__package__).joinpath(f"{name}.md").read_text()
    except (FileNotFoundError, TypeError):
        pass

    raise FileNotFoundError(
        f"Prompt '{name}' not found. Searched:\n"
        f"  - {path}\n"
        f"  - {user_path}\n"
        f"  - (package) agentkb/prompts/{name}.md"
    )
