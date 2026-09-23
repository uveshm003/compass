# Language queries

One directory per language. Adding a language touches nothing else in the core:

| File | Required | Purpose |
| --- | --- | --- |
| `language.yaml` | yes | Grammar name, file matching, doc and visibility rules |
| `tags.scm` | yes | Definitions: what becomes a symbol row and a map-shard line |
| `imports.scm` | no | Import targets for the import graph (IX-11) |

A language only counts as supported once it also has a fixture repo under
`tests/fixtures/` and a passing snapshot test.

## `language.yaml`

```yaml
name: typescript               # must equal the directory name
grammar: typescript            # tree-sitter-language-pack grammar
grammar_by_extension: {.tsx: tsx}
extensions: [.ts, .tsx]
filenames: []                  # exact file names, e.g. Dockerfile
shebangs: [node]               # interpreters, for extensionless scripts
wrappers: [export_statement]   # nodes that wrap a definition; the symbol range
                               # and doc lookup extend to them
skip_before_doc: [decorator]   # siblings allowed between a doc comment and
                               # its definition; they also extend the range
docstring: body_first_string   # optional named docstring rule (see below)
index_files: [index.ts]        # a folder's purpose comes from this file's
                               # header when the folder has no README
visibility:
  modifiers: [["^private$", private]]  # regex over the @visibility capture
  names: [["^#", private]]             # regex over the symbol name
  exported_by: [export_statement]      # declarations are public only inside these
  default: public
```

Docstring rules: `body_first_string` takes the first string literal in the
definition's body (and the module's first statement for the file header), and
falls back to the leading comment.

Visibility is decided in this order: a `@visibility.<value>` capture, a
`@visibility` capture matched against `modifiers`, the `names` rules, the
`exported_by` rule for declarations that are not class-like members, the
enclosing interface or trait's visibility, then `default`.

## `tags.scm` captures

| Capture | Meaning |
| --- | --- |
| `@definition.<kind>` | The definition node; its rows are the symbol's line range |
| `@name` | The symbol name |
| `@parent` | Explicit parent name, for definitions not nested in their owner (Go methods) |
| `@visibility` | Modifier text, mapped through `visibility.modifiers` |
| `@visibility.<value>` | Sets visibility to `<value>` outright |
| `@signature` | The signature starts here instead of at `@name` |
| `@params` | The signature is the name followed by the text from here (functions assigned to variables) |
| `@body` | The signature ends where this node starts; the default is the definition's `body` field, else the end of the name's line |

Captures starting with `_` are helpers for predicates and are ignored.

Kinds in use: `class`, `interface`, `struct`, `enum`, `trait`, `impl`, `type`,
`function`, `method`, `constant`, `variable`, `module`, `namespace`, `macro`.

Rules the core applies to every language:

- When two patterns capture the same node, the earlier pattern wins, so put
  specific patterns first.
- A `function` whose nearest enclosing definition is a class, interface,
  struct, enum, trait or impl becomes a `method`.
- Definitions nested inside a function or method are local and are dropped.

## `imports.scm` captures

`@import`: a node whose text, with quotes stripped, is one import target.
