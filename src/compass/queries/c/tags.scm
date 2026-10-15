; C, for .c files. Headers (.h) go through the cpp query: the C++ grammar parses
; C headers too.

; Signatures start at the return type, after `static`, `inline`, `virtual`,
; `constexpr` and attributes, the way C# and Java read: a `const` or `volatile`
; right before the type is part of it (`const char* label(Level level)`).
; Constructors and destructors have no type and start at their name; an
; out-of-class definition keeps its `Owner::` as written. Every function
; pattern below carries this optional capture.

; Functions. Prototypes in a .c file are forward declarations and are left out;
; `static` functions are private to their file.
(function_definition
  (storage_class_specifier) @visibility.private
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (identifier) @name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
    (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
  ]
  (#eq? @visibility.private "static")) @definition.function

(function_definition
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (identifier) @name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
    (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
  ]) @definition.function

; Named structs, unions and enums with a body. Inside a typedef they are the
; typedef's symbol instead (below).
[
  (translation_unit (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (declaration (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (field_declaration (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_ifdef (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_if (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_else (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_elif (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
]

[
  (translation_unit (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (declaration (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (field_declaration (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_ifdef (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_if (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_else (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_elif (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
]

[
  (translation_unit (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (declaration (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (field_declaration (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (preproc_ifdef (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (preproc_if (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (preproc_else (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (preproc_elif (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
]

; typedefs are one symbol under the typedef's name, even when the struct also
; has a tag: `typedef struct backoff {...} backoff_t;` is backoff_t.
(type_definition
  type: [(struct_specifier body: (_)) (union_specifier body: (_))]
  declarator: (type_identifier) @name) @definition.struct

(type_definition
  type: (enum_specifier body: (_))
  declarator: (type_identifier) @name) @definition.enum

(type_definition
  declarator: [
    (type_identifier) @name
    (pointer_declarator declarator: (type_identifier) @name)
    (function_declarator declarator: (parenthesized_declarator (pointer_declarator declarator: (type_identifier) @name)))
  ]) @definition.type

; Macros with a value or parameters; bare flags and include guards are left out.
(preproc_function_def
  name: (identifier) @name
  value: (_) @body) @definition.macro

(preproc_function_def
  name: (identifier) @name) @definition.macro

(preproc_def
  name: (identifier) @name
  value: (_)) @definition.macro

; Objects at file or namespace scope (inside functions they are local). const
; and constexpr objects are constants; `static` makes either private. Their
; signature starts at the type: the label already says const.
(declaration
  (storage_class_specifier) @visibility.private
  (type_qualifier) @_const
  type: (_)? @signature
  declarator: [
    (identifier) @name
    (pointer_declarator declarator: (identifier) @name)
    (array_declarator declarator: (identifier) @name)
    (init_declarator declarator: (identifier) @name)
    (init_declarator declarator: (pointer_declarator declarator: (identifier) @name))
    (init_declarator declarator: (array_declarator declarator: (identifier) @name))
    (init_declarator declarator: (pointer_declarator declarator: (array_declarator declarator: (identifier) @name)))
  ]
  (#eq? @visibility.private "static")
  (#match? @_const "^const$")) @definition.constant

(declaration
  (type_qualifier) @_const
  type: (_)? @signature
  declarator: [
    (identifier) @name
    (pointer_declarator declarator: (identifier) @name)
    (array_declarator declarator: (identifier) @name)
    (init_declarator declarator: (identifier) @name)
    (init_declarator declarator: (pointer_declarator declarator: (identifier) @name))
    (init_declarator declarator: (array_declarator declarator: (identifier) @name))
    (init_declarator declarator: (pointer_declarator declarator: (array_declarator declarator: (identifier) @name)))
  ]
  (#match? @_const "^const$")) @definition.constant

(declaration
  (storage_class_specifier) @visibility.private
  type: (_)? @signature
  declarator: [
    (identifier) @name
    (pointer_declarator declarator: (identifier) @name)
    (array_declarator declarator: (identifier) @name)
    (init_declarator declarator: (identifier) @name)
    (init_declarator declarator: (pointer_declarator declarator: (identifier) @name))
    (init_declarator declarator: (array_declarator declarator: (identifier) @name))
    (init_declarator declarator: (pointer_declarator declarator: (array_declarator declarator: (identifier) @name)))
  ]
  (#eq? @visibility.private "static")) @definition.variable

(declaration
  type: (_)? @signature
  declarator: [
    (identifier) @name
    (pointer_declarator declarator: (identifier) @name)
    (array_declarator declarator: (identifier) @name)
    (init_declarator declarator: (identifier) @name)
    (init_declarator declarator: (pointer_declarator declarator: (identifier) @name))
    (init_declarator declarator: (array_declarator declarator: (identifier) @name))
    (init_declarator declarator: (pointer_declarator declarator: (array_declarator declarator: (identifier) @name)))
  ]) @definition.variable

; References: call sites, for callers_of. Matched by name only; plain calls
; first, then calls through a struct member.
(call_expression function: (identifier) @name) @reference.call
(call_expression function: (field_expression field: (field_identifier) @name)) @reference.call
