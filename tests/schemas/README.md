# Vendored JSON schemas

Copies of SchemaStore's schemas for Claude Code plugin files, so
`tests/test_plugin.py` validates `plugin/` and `.claude-plugin/` offline, on
every CI run.

| File | Source |
| --- | --- |
| `claude-code-plugin-manifest.json` | https://json.schemastore.org/claude-code-plugin-manifest.json |
| `claude-code-marketplace.json` | https://json.schemastore.org/claude-code-marketplace.json |

Fetched 2026-09-23. SchemaStore publishes its schemas under the Apache License
2.0. They are community-maintained, so `claude plugin validate --strict plugin`
(run by the same test when Claude Code is installed) stays the authority;
refresh these copies when the plugin format changes.
