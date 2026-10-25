; Dart puts a function's signature beside its body rather than around it, so a
; function or method with a body is captured as its function_body: the range
; then covers the whole function, and skip_before_doc carries it back over the
; signature and annotations. The body is also @body, so the signature ends
; where the body starts. Members without a body are their declaration.
; A function, getter, setter or operator signature node starts at its return
; type when one is written (after modifiers such as static and external, which
; sit outside it), so it is the @signature; constructors start at their name.

; Classes, interfaces, mixins, extensions, enums
(class_definition
  (interface)
  name: (identifier) @name) @definition.interface

(class_definition
  name: (identifier) @name) @definition.class

(mixin_declaration
  (identifier) @name
  (class_body) @body) @definition.trait

(extension_declaration
  name: (identifier) @name) @definition.impl

; An unnamed extension is named after the type it extends, like a Rust impl.
(extension_declaration
  !name
  class: (_) @name) @definition.impl

(extension_type_declaration
  name: (identifier) @name) @definition.class

(enum_declaration
  name: (identifier) @name) @definition.enum

; typedef Handler = void Function(String); typedef int Compare(int a, int b);
(type_alias
  (type_identifier) @name . "=") @definition.type

(type_alias
  (type_identifier) @name . (type_parameters) . "=") @definition.type

(type_alias
  (type_identifier) @name . (type_parameters)? . (formal_parameter_list)) @definition.type

; Top-level functions, getters and setters
(program
  [
    (function_signature name: (identifier) @name)
    (getter_signature name: (identifier) @name)
    (setter_signature name: (identifier) @name)
  ] @signature
  .
  (function_body) @body @definition.function)

; Members with a body: methods, getters, setters, operators, constructors
(_
  (method_signature
    [
      (function_signature name: (identifier) @name) @signature
      (getter_signature name: (identifier) @name) @signature
      (setter_signature name: (identifier) @name) @signature
      (operator_signature (binary_operator) @name) @signature
      (constructor_signature name: (identifier) @name . parameters: (formal_parameter_list))
      (factory_constructor_signature (identifier) @name . (formal_parameter_list))
    ])
  .
  (function_body) @body @definition.function)

; Members without a body: abstract and external members, constructors ending in `;`
(declaration
  [
    (function_signature name: (identifier) @name) @signature
    (getter_signature name: (identifier) @name) @signature
    (setter_signature name: (identifier) @name) @signature
    (constructor_signature name: (identifier) @name . parameters: (formal_parameter_list))
    (constant_constructor_signature (identifier) @name . (formal_parameter_list))
    (factory_constructor_signature (identifier) @name . (formal_parameter_list))
    (redirecting_factory_constructor_signature (identifier) @name . (formal_parameter_list))
  ]) @definition.function

; Constants: top-level const and final, and static ones in a class. Instance
; fields are left out, as in the other languages. A written type starts the
; signature (`int maxAttempts = 5`); these typed forms come first, so they win
; over the untyped ones below for the same name.
(program
  [
    ((type_identifier) @signature)
    ((type_identifier) @signature . (type_arguments))
    ((type_identifier) @signature . (nullable_type))
    ((type_identifier) @signature . (type_arguments) . (nullable_type))
    ((function_type) @signature)
    ((function_type) @signature . (nullable_type))
  ]
  .
  (static_final_declaration_list
    (static_final_declaration . (identifier) @name) @definition.constant))

(declaration
  "static"
  [
    ((type_identifier) @signature)
    ((type_identifier) @signature . (type_arguments))
    ((type_identifier) @signature . (nullable_type))
    ((type_identifier) @signature . (type_arguments) . (nullable_type))
    ((function_type) @signature)
    ((function_type) @signature . (nullable_type))
  ]
  .
  (static_final_declaration_list
    (static_final_declaration . (identifier) @name) @definition.constant))

(program
  [
    ((type_identifier) @signature)
    ((type_identifier) @signature . (type_arguments))
    ((type_identifier) @signature . (nullable_type))
    ((type_identifier) @signature . (type_arguments) . (nullable_type))
    ((function_type) @signature)
    ((function_type) @signature . (nullable_type))
  ]
  .
  (initialized_identifier_list
    (initialized_identifier . (identifier) @name) @definition.variable))

(program
  (static_final_declaration_list
    (static_final_declaration . (identifier) @name) @definition.constant))

(declaration
  "static"
  (static_final_declaration_list
    (static_final_declaration . (identifier) @name) @definition.constant))

(program
  (initialized_identifier_list
    (initialized_identifier . (identifier) @name) @definition.variable))

; References: call sites, for callers_of. Matched by name only.
; f(), Reading(2)
(_
  (identifier) @name
  .
  (selector (argument_part))) @reference.call

; a.b(), a?.b()
(_
  (selector
    [
      (unconditional_assignable_selector (identifier) @name)
      (conditional_assignable_selector (identifier) @name)
    ])
  .
  (selector (argument_part))) @reference.call

; super.b()
(_
  (unconditional_assignable_selector (identifier) @name)
  .
  (selector (argument_part))) @reference.call

; a..b()
(cascade_section
  (cascade_selector (identifier) @name)
  .
  (argument_part)) @reference.call

; new Reading(1), const Reading(), and their named forms new Reading.zero()
(new_expression
  (type_identifier) @name . (arguments)) @reference.call

(new_expression
  (type_identifier) . (identifier) @name) @reference.call

(const_object_expression
  (type_identifier) @name . (arguments)) @reference.call

(const_object_expression
  (type_identifier) . (identifier) @name) @reference.call
