; Annotations live inside `modifiers`, so a definition's range and doc already
; include them.

; Types. A record's components and a class's extends/implements end the
; signature at the body.
(class_declaration
  (modifiers)? @visibility
  name: (identifier) @name) @definition.class

(record_declaration
  (modifiers)? @visibility
  name: (identifier) @name) @definition.class

(interface_declaration
  (modifiers)? @visibility
  name: (identifier) @name) @definition.interface

(annotation_type_declaration
  (modifiers)? @visibility
  name: (identifier) @name) @definition.interface

(enum_declaration
  (modifiers)? @visibility
  name: (identifier) @name) @definition.enum

; Methods. The signature starts at the type parameters or the return type:
; "<T> List<T> sorted(Comparator<T> by) throws IOException".
(method_declaration
  (modifiers)? @visibility
  type_parameters: (_) @signature
  name: (identifier) @name) @definition.method

(method_declaration
  (modifiers)? @visibility
  type: (_) @signature
  name: (identifier) @name) @definition.method

(constructor_declaration
  (modifiers)? @visibility
  name: (identifier) @name) @definition.method

; Constants: static final fields, and every field of an interface. The
; signature starts at the type: "double DEFAULT_THRESHOLD = 40.0".
(field_declaration
  (modifiers) @visibility
  type: (_) @signature
  declarator: (variable_declarator
    name: (identifier) @name)
  (#match? @visibility "\\bstatic\\b")
  (#match? @visibility "\\bfinal\\b")) @definition.constant

(constant_declaration
  (modifiers)? @visibility
  type: (_) @signature
  declarator: (variable_declarator
    name: (identifier) @name)) @definition.constant

; References: call sites and `new`, for callers_of. Matched by name only.
(method_invocation
  name: (identifier) @name) @reference.call

(object_creation_expression
  type: [
    (type_identifier) @name
    (scoped_type_identifier (type_identifier) @name .)
    (generic_type [(type_identifier) @name (scoped_type_identifier (type_identifier) @name .)])
  ]) @reference.call

; Method references (Reading::isAlarm) pass a method to be called later.
(method_reference
  (identifier) @name .) @reference.call
