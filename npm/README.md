# compass-cc

The one-command installer for Compass, the layer that gives Claude Code a code map, request and spec gates, Haiku subagents and a review manifest for every change.

```bash
npx compass-cc install                      # asks: for you or the whole repo, plugin or files, which modules
npx compass-cc install --yes --scope project --mode files
npx compass-cc install --source git+https://github.com/<owner>/<repo>    # the CLI from a git repo instead of the package index
npx compass-cc doctor | upgrade | uninstall
```

This package holds no logic of its own. It finds [uv](https://docs.astral.sh/uv/), or installs it once you agree. Then it installs the `compass` CLI at the same version as this package (`uv tool install compass==<version>`) and passes every argument to `compass install`. Without Node, the same works through uv alone:

```bash
uvx --from git+https://github.com/<owner>/<repo> compass install
```

Compass works through Claude Code and your own Claude login. It never asks for an API key.

The product name is Compass, but this package name is still a placeholder: `compass-cc` is taken on npmjs by another project, so the published name (for example a scoped `@<org>/compass` in the Azure Artifacts feed) is still to be chosen.
