; `import a.b.C;`, `import static a.b.C.member;` and `import a.b.*;` (the
; package: it resolves to its package-info.java when there is one).
(import_declaration
  [(scoped_identifier) (identifier)] @import)
