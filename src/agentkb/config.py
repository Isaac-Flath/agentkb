import json
from pathlib import Path


def find_in_project_wiki(project_root: Path) -> Path | None:
    """Check if a directory has an in-project wiki override."""
    for candidate in [project_root / ".agentkb" / "wiki", project_root / ".knowledge"]:
        if candidate.exists():
            return candidate
    return None


class paths:
    """Central path resolution for agentkb directories."""

    @staticmethod
    def agentkb_home() -> Path:
        return Path.home() / ".agentkb"

    @staticmethod
    def wiki_dir() -> Path:
        """Global wiki directory. Checks settings override, then in-project override, then default."""
        custom = Settings().get("wiki_path")
        if custom:
            return Path(custom).expanduser()
        local_kb = find_in_project_wiki(Path(".").resolve())
        if local_kb:
            return local_kb
        return paths.agentkb_home() / "wiki"

    @staticmethod
    def chats_dir() -> Path:
        """Root directory for chat history."""
        custom = Settings().get("chats_path")
        if custom:
            return Path(custom).expanduser()
        return paths.agentkb_home() / "chats"

    @staticmethod
    def communications_dir() -> Path:
        """Root directory for human communications and transcripts."""
        custom = Settings().get("communications_path")
        if custom:
            return Path(custom).expanduser()
        return paths.agentkb_home() / "communications"

    @staticmethod
    def references_dir() -> Path:
        """Root directory for watched external references and mirrors."""
        custom = Settings().get("references_path")
        if custom:
            return Path(custom).expanduser()
        return paths.agentkb_home() / "references"

    @staticmethod
    def chats_sessions_dir() -> Path:
        """Agentkb-owned copy of chat JSONL files. This is what syncs."""
        return paths.chats_dir() / "sessions"

    @staticmethod
    def chats_readable_dir() -> Path:
        """Readable markdown exports of chat sessions. This is what syncs and gets indexed."""
        return paths.chats_dir() / "readable"

    @staticmethod
    def claude_projects_dir() -> Path:
        """Source directory for Claude Code conversation JSONL files."""
        return Path.home() / ".claude" / "projects"

    @staticmethod
    def pi_sessions_dir() -> Path:
        """Source directory for Pi conversation JSONL files."""
        return Path.home() / ".pi" / "agent" / "sessions"

    @staticmethod
    def skills_dir() -> Path:
        """Skills directory. Not indexed — just filesystem presence for --add-dir."""
        custom = Settings().get("skills_path")
        if custom:
            return Path(custom).expanduser()
        return paths.agentkb_home() / "skills"

    @staticmethod
    def config_file() -> Path:
        return paths.agentkb_home() / "config.json"


SETTINGS_DEFAULTS = {
    "default_scope": "wiki",
    "top_k": 15,
    "wiki_path": "",
    "wiki_remote": "",
    "chats_path": "",
    "chats_remote": "",
    "communications_path": "",
    "communications_remote": "",
    "references_path": "",
    "skills_path": "",
    "skills_remote": "",
    "traceability_s3_bucket": "",  # e.g. "isaacflath-private"
    "traceability_s3_key": "agentkb/traceability.db",
}


class Settings:
    """Read/write ~/.agentkb/config.json."""

    def __init__(self):
        self._path = paths.config_file()
        self._data = dict(SETTINGS_DEFAULTS)
        if self._path.exists():
            with open(self._path) as f:
                self._data.update(json.load(f))

    def get(self, key: str):
        return self._data.get(key, SETTINGS_DEFAULTS.get(key))

    def set(self, key: str, value: str):
        # Coerce types based on defaults
        default = SETTINGS_DEFAULTS.get(key)
        if isinstance(default, int):
            value = int(value)
        self._data[key] = value
        self._save()

    def all(self) -> dict:
        return dict(self._data)

    def _save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)
            f.write("\n")
