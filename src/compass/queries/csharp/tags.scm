
; Namespaces. A block-scoped namespace contains its types, so they get it as
; their parent; a file-scoped one (`namespace A.B;`) is a one-line symbol.
(namespace_declaration
  name: (_) @name @visibility.public) @definition.namespace

(file_scoped_namespace_declaration
  name: (_) @name @visibility.public) @definition.namespace

; Types with an access modifier. Every type pattern comes three times: with an
; access modifier, at the top level without one (internal), and nested without
; one (private, the language default). The earlier pattern wins.
(class_declaration
  (modifier) @visibility
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.class

(record_declaration
  (modifier) @visibility
  "struct"
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.struct

(record_declaration
  (modifier) @visibility
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.class

(struct_declaration
  (modifier) @visibility
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.struct

(interface_declaration
  (modifier) @visibility
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.interface

(enum_declaration
  (modifier) @visibility
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.enum

(delegate_declaration
  (modifier) @visibility
  type: (_) @signature
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.type

; Top-level types without an access modifier are internal.
(compilation_unit
  [
    (class_declaration name: (identifier) @name @visibility.internal) @definition.class
    (record_declaration "struct" name: (identifier) @name @visibility.internal) @definition.struct
    (record_declaration name: (identifier) @name @visibility.internal) @definition.class
    (struct_declaration name: (identifier) @name @visibility.internal) @definition.struct
    (interface_declaration name: (identifier) @name @visibility.internal) @definition.interface
    (enum_declaration name: (identifier) @name @visibility.internal) @definition.enum
    (delegate_declaration type: (_) @signature name: (identifier) @name @visibility.internal) @definition.type
  ])

(namespace_declaration
  body: (declaration_list
    [
      (class_declaration name: (identifier) @name @visibility.internal) @definition.class
      (record_declaration "struct" name: (identifier) @name @visibility.internal) @definition.struct
      (record_declaration name: (identifier) @name @visibility.internal) @definition.class
      (struct_declaration name: (identifier) @name @visibility.internal) @definition.struct
      (interface_declaration name: (identifier) @name @visibility.internal) @definition.interface
      (enum_declaration name: (identifier) @name @visibility.internal) @definition.enum
      (delegate_declaration type: (_) @signature name: (identifier) @name @visibility.internal) @definition.type
    ]))

; Nested types without an access modifier: private.
(class_declaration
  name: (identifier) @name) @definition.class

(record_declaration
  "struct"
  name: (identifier) @name) @definition.struct

(record_declaration
  name: (identifier) @name) @definition.class

(struct_declaration
  name: (identifier) @name) @definition.struct

(interface_declaration
  name: (identifier) @name) @definition.interface

(enum_declaration
  name: (identifier) @name) @definition.enum

(delegate_declaration
  type: (_) @signature
  name: (identifier) @name) @definition.type

; Methods and constructors. A method's signature starts at its return type;
; interface members without a modifier take the interface's visibility.
(method_declaration
  (modifier) @visibility
  returns: (_) @signature
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.method

(method_declaration
  returns: (_) @signature
  name: (identifier) @name) @definition.method

(constructor_declaration
  (modifier) @visibility
  name: (identifier) @name
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.method

(constructor_declaration
  name: (identifier) @name) @definition.method

; Properties with code behind them (`=> expr`, or an accessor with a body)
; are methods, as getters are in TypeScript; auto-properties are data and are
; left out, like fields.
(property_declaration
  (modifier) @visibility
  type: (_) @signature
  name: (identifier) @name
  value: (arrow_expression_clause) @body
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.method

(property_declaration
  (modifier) @visibility
  type: (_) @signature
  name: (identifier) @name
  accessors: (accessor_list
    (accessor_declaration
      body: (_))) @body
  (#match? @visibility "^(public|private|protected|internal)$")) @definition.method

(property_declaration
  type: (_) @signature
  name: (identifier) @name
  value: (arrow_expression_clause) @body) @definition.method

(property_declaration
  type: (_) @signature
  name: (identifier) @name
  accessors: (accessor_list
    (accessor_declaration
      body: (_))) @body) @definition.method

; Constants: `const` and `static readonly` fields.
(field_declaration
  (modifier) @visibility
  (modifier) @_const
  (variable_declaration
    type: (_) @signature
    (variable_declarator
      name: (identifier) @name))
  (#match? @visibility "^(public|private|protected|internal)$")
  (#eq? @_const "const")) @definition.constant

(field_declaration
  (modifier) @visibility
  (modifier) @_static
  (modifier) @_readonly
  (variable_declaration
    type: (_) @signature
    (variable_declarator
      name: (identifier) @name))
  (#match? @visibility "^(public|private|protected|internal)$")
  (#eq? @_static "static")
  (#eq? @_readonly "readonly")) @definition.constant

(field_declaration
  (modifier) @_const
  (variable_declaration
    type: (_) @signature
    (variable_declarator
      name: (identifier) @name))
  (#eq? @_const "const")) @definition.constant

(field_declaration
  (modifier) @_static
  (modifier) @_readonly
  (variable_declaration
    type: (_) @signature
    (variable_declarator
      name: (identifier) @name))
  (#eq? @_static "static")
  (#eq? @_readonly "readonly")) @definition.constant

; References: call sites and `new T(...)`, for callers_of. Matched by name only.
(invocation_expression
  function: (identifier) @name) @reference.call

(invocation_expression
  function: (generic_name
    (identifier) @name)) @reference.call

(invocation_expression
  function: (member_access_expression
    name: (identifier) @name)) @reference.call

(invocation_expression
  function: (member_access_expression
    name: (generic_name
      (identifier) @name))) @reference.call

(invocation_expression
  function: (conditional_access_expression
    (member_binding_expression
      name: (identifier) @name))) @reference.call

(object_creation_expression
  type: (identifier) @name) @reference.call

(object_creation_expression
  type: (generic_name
    (identifier) @name)) @reference.call

(object_creation_expression
  type: (qualified_name
    name: (identifier) @name)) @reference.call
