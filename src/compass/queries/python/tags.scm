; Classes. Functions inside a class become methods automatically.
(class_definition
  name: (identifier) @name) @definition.class

(function_definition
  name: (identifier) @name) @definition.function

; Module-level constants: UPPER_CASE names only, so ordinary module state
; stays out of the map.
(module
  (assignment
    left: (identifier) @name) @definition.constant
  (#match? @name "^_?[A-Z][A-Z0-9_]*$"))
