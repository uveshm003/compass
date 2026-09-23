(function_declaration
  name: (identifier) @name) @definition.function

; Methods live outside their type, so the receiver names the parent.
(method_declaration
  receiver: (parameter_list
    (parameter_declaration
      type: [
        (type_identifier) @parent
        (pointer_type (type_identifier) @parent)
        (generic_type type: (type_identifier) @parent)
        (pointer_type (generic_type type: (type_identifier) @parent))
      ]))
  name: (field_identifier) @name) @definition.method

; Types. The struct and interface bodies end the signature.
(type_spec
  name: (type_identifier) @name
  type: (struct_type) @body) @definition.struct

(type_spec
  name: (type_identifier) @name
  type: (interface_type) @body) @definition.interface

(type_spec
  name: (type_identifier) @name) @definition.type

(type_alias
  name: (type_identifier) @name) @definition.type

(interface_type
  (method_elem
    name: (field_identifier) @name) @definition.method)

; Package-level constants and variables. The names are matched without their
; `name:` field: with it, `const A, B = 1, 2` yields only A. Values and types
; are never direct identifier children, so this still matches names only.
(source_file
  (const_declaration
    (const_spec
      (identifier) @name) @definition.constant))

(source_file
  (var_declaration
    (var_spec
      (identifier) @name) @definition.variable))

(source_file
  (var_declaration
    (var_spec_list
      (var_spec
        (identifier) @name) @definition.variable)))

; References: call sites, for callers_of. Matched by name only.
(call_expression
  function: (identifier) @name) @reference.call

(call_expression
  function: (selector_expression
    field: (field_identifier) @name)) @reference.call
