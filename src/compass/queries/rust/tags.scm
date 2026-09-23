; Types
(struct_item
  (visibility_modifier)? @visibility
  name: (type_identifier) @name) @definition.struct

(union_item
  (visibility_modifier)? @visibility
  name: (type_identifier) @name) @definition.struct

(enum_item
  (visibility_modifier)? @visibility
  name: (type_identifier) @name) @definition.enum

(trait_item
  (visibility_modifier)? @visibility
  name: (type_identifier) @name) @definition.trait

(type_item
  (visibility_modifier)? @visibility
  name: (type_identifier) @name) @definition.type

; impl blocks group their methods. A trait impl's signature starts at the
; trait: "fmt::Display for Point<i32>".
(impl_item
  trait: (_) @signature
  type: [
    (type_identifier) @name
    (generic_type type: (type_identifier) @name)
    (scoped_type_identifier name: (type_identifier) @name)
  ]) @definition.impl

(impl_item
  !trait
  type: [
    (type_identifier) @name
    (generic_type type: (type_identifier) @name)
    (scoped_type_identifier name: (type_identifier) @name)
  ]) @definition.impl

; Methods of a trait impl are as visible as the trait itself.
(impl_item
  trait: (_) @visibility.public
  body: (declaration_list
    (function_item
      name: (identifier) @name) @definition.function))

; Functions; those inside impl and trait blocks become methods automatically.
(function_item
  (visibility_modifier)? @visibility
  name: (identifier) @name) @definition.function

(function_signature_item
  (visibility_modifier)? @visibility
  name: (identifier) @name) @definition.function

; Modules with a body; `mod foo;` only points at another file.
(mod_item
  (visibility_modifier)? @visibility
  name: (identifier) @name
  body: (declaration_list)) @definition.module

(macro_definition
  name: (identifier) @name
  .
  (macro_rule) @body) @definition.macro

(const_item
  (visibility_modifier)? @visibility
  name: (identifier) @name) @definition.constant

(static_item
  (visibility_modifier)? @visibility
  name: (identifier) @name) @definition.constant

; References: call sites, for callers_of. Matched by name only.
(call_expression
  function: (identifier) @name) @reference.call

(call_expression
  function: (field_expression
    field: (field_identifier) @name)) @reference.call

(call_expression
  function: (scoped_identifier
    name: (identifier) @name)) @reference.call

(call_expression
  function: (generic_function
    function: [
      (identifier) @name
      (scoped_identifier name: (identifier) @name)
      (field_expression field: (field_identifier) @name)
    ])) @reference.call

; Inside macro arguments (assert!, vec!, println!) there are no expressions,
; only tokens: an identifier directly followed by a parenthesised group is a call.
(token_tree
  (identifier) @name
  .
  (token_tree) @_args
  (#match? @_args "^\\(")) @reference.call
