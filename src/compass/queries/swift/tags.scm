; Types. class, struct, enum, actor and extension all parse as
; class_declaration; declaration_kind says which. The whole `modifiers` node is
; the @visibility capture (see language.yaml).
(class_declaration
  (modifiers)? @visibility
  declaration_kind: "struct"
  name: (type_identifier) @name) @definition.struct

(class_declaration
  (modifiers)? @visibility
  declaration_kind: "enum"
  name: (type_identifier) @name) @definition.enum

(class_declaration
  (modifiers)? @visibility
  declaration_kind: ["class" "actor"]
  name: (type_identifier) @name) @definition.class

; An extension groups methods under the type it extends, like a Rust impl.
(class_declaration
  declaration_kind: "extension"
  name: (user_type
    (type_identifier) @name)) @definition.impl

(protocol_declaration
  (modifiers)? @visibility
  name: (type_identifier) @name) @definition.interface

(typealias_declaration
  (modifiers)? @visibility
  name: (type_identifier) @name) @definition.type

; Functions; those inside types and extensions become methods automatically.
(function_declaration
  (modifiers)? @visibility
  name: (simple_identifier) @name) @definition.function

(protocol_function_declaration
  (modifiers)? @visibility
  name: (simple_identifier) @name) @definition.function

(init_declaration
  (modifiers)? @visibility
  name: "init" @name) @definition.function

; Constants and variables at file level, and static constants of a type.
; Instance properties are left out, as other languages leave out fields.
(source_file
  (property_declaration
    (modifiers)? @visibility
    (value_binding_pattern
      mutability: "let")
    name: (pattern
      bound_identifier: (simple_identifier) @name)) @definition.constant)

(source_file
  (property_declaration
    (modifiers)? @visibility
    (value_binding_pattern
      mutability: "var")
    name: (pattern
      bound_identifier: (simple_identifier) @name)) @definition.variable)

(class_body
  (property_declaration
    (modifiers) @visibility
    (value_binding_pattern
      mutability: "let")
    name: (pattern
      bound_identifier: (simple_identifier) @name)
    (#match? @visibility "(^|\\s)static(\\s|$)")) @definition.constant)

(enum_class_body
  (property_declaration
    (modifiers) @visibility
    (value_binding_pattern
      mutability: "let")
    name: (pattern
      bound_identifier: (simple_identifier) @name)
    (#match? @visibility "(^|\\s)static(\\s|$)")) @definition.constant)

; References: call sites, for callers_of. Matched by name only. A type's name
; called like a function is its initializer: Reading(sensorId: ...).
(call_expression
  .
  (simple_identifier) @name) @reference.call

(call_expression
  .
  (navigation_expression
    suffix: (navigation_suffix
      suffix: (simple_identifier) @name))) @reference.call

(constructor_expression
  constructed_type: (user_type
    (type_identifier) @name)) @reference.call
