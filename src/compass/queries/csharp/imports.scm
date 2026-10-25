; `using X.Y;`, `using static X.Y;`, `global using X.Y;` and the target of an
; alias (`using Z = X.Y;`), whose own name is left out.
(using_directive
  (qualified_name) @import)

(using_directive
  !name
  (identifier) @import)
