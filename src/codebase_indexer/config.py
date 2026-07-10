"""Central configuration constants for the codebase indexer MCP server."""

SERVER_NAME = "codebase-indexer-mcp"

DEFAULT_INDEX_DIR_NAME = ".codebase-index"
DEFAULT_COLLECTION_NAME = "codebase_indexer"

MAX_FILE_SIZE_BYTES = 300 * 1024

DEFAULT_CHUNK_SIZE_LINES = 80
DEFAULT_CHUNK_OVERLAP_LINES = 10

INDEX_EXTENSIONS = frozenset(
    {
        ".go",
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".md",
        ".sh",
        ".sql",
    }
)

INDEX_FILENAMES = frozenset(
    {
        "Dockerfile",
        "Makefile",
        "Taskfile.yml",
        "docker-compose.yml",
        "compose.yml",
        "go.mod",
        "go.sum",
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "pyproject.toml",
        "requirements.txt",
        "README.md",
    }
)

SKIP_DIRECTORIES = frozenset(
    {
        ".git",
        ".codebase-index",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        "vendor",
        "dist",
        "build",
        ".next",
        ".pytest_cache",
        ".mypy_cache",
        "coverage",
    }
)
