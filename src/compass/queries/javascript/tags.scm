; Classes and their members
(class_declaration
  name: (identifier) @name) @definition.class

(class_body
  (method_definition
    name: [(property_identifier) (private_property_identifier)] @name) @definition.method)

; Class fields that hold functions: handler = (e) => { ... }
(field_definition
  property: [(property_identifier) (private_property_identifier)] @name
  value: (arrow_function
    parameters: (_) @params
    body: (_) @body)) @definition.method

(field_definition
  property: [(property_identifier) (private_property_identifier)] @name
  value: (arrow_function
    parameter: (_) @params
    body: (_) @body)) @definition.method

; Functions
(function_declaration
  name: (identifier) @name) @definition.function

(generator_function_declaration
  name: (identifier) @name) @definition.function

; Functions assigned to variables: const withRetry = async (op) => ...
(variable_declarator
  name: (identifier) @name
  value: (arrow_function
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
    parameters: (_) @params
    body: (_) @body)) @definition.function

(variable_declarator
  name: (identifier) @name
  value: (generator_function
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

; References: call sites (and `new`), for callers_of. Matched by name only.
(call_expression
  function: (identifier) @name) @reference.call

(call_expression
  function: (member_expression
    property: [(property_identifier) (private_property_identifier)] @name)) @reference.call

(new_expression
  constructor: (identifier) @name) @reference.call
