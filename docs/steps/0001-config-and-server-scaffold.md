# 0001 Config and Server Scaffold

Date: 2026-07-09
Status: implemented

## Goal

Create the first narrow scaffold step for the MCP server by establishing central
configuration constants and the FastMCP server entrypoint.

## Changes

- Added package initialization in `src/codebase_indexer/__init__.py`.
- Expanded `src/codebase_indexer/config.py` with server, index, file selection,
  skip directory, file size, and chunking constants.
- Updated `src/codebase_indexer/server.py` to use the configured server name.
- Added placeholder MCP tools for the planned v0 tool surface.
- Added the `docs/steps/` convention for small chronological development notes.

## Decisions

- Keep configuration centralized in `config.py` before building helper modules.
- Register the planned MCP tool names early, but raise explicit `ToolError`
  failures until indexing behavior exists.
- Import `FastMCP` from the declared `fastmcp` dependency instead of relying on
  transitive `mcp` package imports.
- Use small step records instead of a single long decisions document.

## Rationale

Centralizing constants first gives later file filtering, chunking, and index
storage work a stable source of truth. Registering the tool surface now makes
the server shape visible without pretending the indexer is already functional.
Raising `ToolError` keeps placeholder tools from being mistaken for successful
results. Small step records preserve context for future LLM and human readers
without creating one large decision log.

## Tests

- Parse Python source for `src/codebase_indexer`.
- Import `codebase_indexer.config` and verify the configured server name.
- Import `codebase_indexer.server` through Pipenv and verify FastMCP
  construction succeeds.

## Follow-ups

- Add `file_finder.py` and tests for file selection.
- Add `chunker.py` and tests for line-based chunking.
- Add `hashing.py` and tests for SHA-256 file hashing.
- Add a runnable server entrypoint once the package layout settles.
- Wire real MCP tool behavior after the pure modules are in place.
