; Also used for .tsx files, whose grammar has the same node types plus JSX.

; Classes and their members
(class_declaration
  name: (type_identifier) @name) @definition.class

(abstract_class_declaration
  name: (type_identifier) @name) @definition.class

(class_body
  (method_definition
    (accessibility_modifier)? @visibility
    name: [(property_identifier) (private_property_identifier)] @name) @definition.method)

(class_body
  (abstract_method_signature
    (accessibility_modifier)? @visibility
    name: (property_identifier) @name) @definition.method)

(class_body
  (method_signature
    (accessibility_modifier)? @visibility
    name: (property_identifier) @name) @definition.method)

; Class fields that hold functions: handler = (e: Event) => { ... }
(public_field_definition
  (accessibility_modifier)? @visibility
  name: [(property_identifier) (private_property_identifier)] @name
  value: (arrow_function
    type_parameters: (_)? @params
    parameters: (_) @params
    body: (_) @body)) @definition.method

(public_field_definition
  (accessibility_modifier)? @visibility
  name: [(property_identifier) (private_property_identifier)] @name
  value: (arrow_function
    parameter: (_) @params
    body: (_) @body)) @definition.method

; Interfaces, types, enums, namespaces
(interface_declaration
  name: (type_identifier) @name) @definition.interface

(interface_body
  (method_signature
    name: (property_identifier) @name) @definition.method)

(type_alias_declaration
  name: (type_identifier) @name) @definition.type

(enum_declaration
  name: (identifier) @name) @definition.enum

(internal_module
  name: [(identifier) (nested_identifier)] @name) @definition.namespace

(module
  name: (string) @name) @definition.module

; Functions, including overload and ambient signatures
(function_declaration
  name: (identifier) @name) @definition.function

(generator_function_declaration
  name: (identifier) @name) @definition.function

(function_signature
  name: (identifier) @name) @definition.function

; Functions assigned to variables: const withRetry = async <T>(op) => ...
(variable_declarator
  name: (identifier) @name
  value: (arrow_function
    type_parameters: (_)? @params
    parameters: (_) @params
    body: (_) @body)) @definition.function

(variable_declarator
  name: (identifier) @name
  value: (arrow_function
    parameter: (_) @params
    body: (_) @body)) @definition.function

(variable_declarator
  name: (identifier) @name
  value: (function_expression
    type_parameters: (_)? @params
    parameters: (_) @params
    body: (_) @body)) @definition.function

; Constants: every exported one, plus UPPER_CASE module-level ones
(export_statement
  declaration: (lexical_declaration
    (variable_declarator
      name: (identifier) @name) @definition.constant))

(program
  (lexical_declaration
    (variable_declarator
      name: (identifier) @name) @definition.constant)
  (#match? @name "^_?[A-Z][A-Z0-9_]*$"))
