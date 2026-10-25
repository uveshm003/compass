; C++, and C headers (.h): the C++ grammar parses both.

; Signatures start at the return type, after `static`, `inline`, `virtual`,
; `constexpr` and attributes, the way C# and Java read: a `const` or `volatile`
; right before the type is part of it (`const char* label(Level level)`).
; Constructors and destructors have no type and start at their name; an
; out-of-class definition keeps its `Owner::` as written. Every function
; pattern below but GoogleTest's carries this optional capture.

; GoogleTest cases: TEST(Suite, Name) { ... } is the function Name in Suite.
(function_definition
  declarator: (function_declarator
    declarator: (identifier) @_macro
    parameters: (parameter_list
      .
      (parameter_declaration type: (type_identifier) @parent)
      .
      (parameter_declaration type: (type_identifier) @name)
      ")" @body))
  (#match? @_macro "^(TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)$")) @definition.function

; Class members take the nearest access specifier above them: no other
; specifier may sit in between.
(field_declaration_list
  (access_specifier) @visibility
  .
  (_)* @_between
  .
  [
    (field_declaration
      ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
      declarator: [
        (function_declarator declarator: [(field_identifier) (operator_name) (destructor_name)] @name)
        (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
      ]) @definition.function
    (declaration
      ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
      declarator: (function_declarator
        declarator: [(identifier) (field_identifier) (destructor_name) (operator_name)] @name)) @definition.function
    (function_definition
      ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
      declarator: [
        (function_declarator declarator: [(field_identifier) (identifier) (destructor_name) (operator_name)] @name)
        (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
      ]) @definition.function
    (template_declaration
      [
        (declaration
          ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
          declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
        (field_declaration
          ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
          declarator: (function_declarator declarator: (field_identifier) @name)) @definition.function
        (function_definition
          ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
          declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
      ])
    (field_declaration type: (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
    (field_declaration type: (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
    (field_declaration type: (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
    (field_declaration type: (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
    (alias_declaration name: (type_identifier) @name) @definition.type
    (type_definition declarator: (type_identifier) @name) @definition.type
  ]
  (#not-match? @_between "^(public|private|protected)$"))

; Members above the first specifier: private in a class, public in a struct or union.
(class_specifier
  body: (field_declaration_list
    .
    (_)* @_between
    .
    [
      (field_declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: [(field_identifier) (operator_name) (destructor_name)] @name)
          (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
          (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        ]) @definition.function
      (declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: (function_declarator
          declarator: [(identifier) (field_identifier) (destructor_name) (operator_name)] @name)) @definition.function
      (function_definition
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: [(field_identifier) (identifier) (destructor_name) (operator_name)] @name)
          (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
          (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        ]) @definition.function
      (template_declaration
        [
          (declaration
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
          (field_declaration
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: (field_identifier) @name)) @definition.function
          (function_definition
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
        ])
      (field_declaration type: (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
      (field_declaration type: (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
      (field_declaration type: (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
      (field_declaration type: (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
      (alias_declaration name: (type_identifier) @name) @definition.type
      (type_definition declarator: (type_identifier) @name) @definition.type
    ]
    (#not-match? @_between "^(public|private|protected)$"))) @visibility.private

(struct_specifier
  body: (field_declaration_list
    .
    (_)* @_between
    .
    [
      (field_declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: [(field_identifier) (operator_name) (destructor_name)] @name)
          (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
          (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        ]) @definition.function
      (declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: (function_declarator
          declarator: [(identifier) (field_identifier) (destructor_name) (operator_name)] @name)) @definition.function
      (function_definition
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: [(field_identifier) (identifier) (destructor_name) (operator_name)] @name)
          (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
          (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        ]) @definition.function
      (template_declaration
        [
          (declaration
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
          (field_declaration
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: (field_identifier) @name)) @definition.function
          (function_definition
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
        ])
      (field_declaration type: (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
      (field_declaration type: (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
      (field_declaration type: (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
      (field_declaration type: (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
      (alias_declaration name: (type_identifier) @name) @definition.type
      (type_definition declarator: (type_identifier) @name) @definition.type
    ]
    (#not-match? @_between "^(public|private|protected)$"))) @visibility.public

(union_specifier
  body: (field_declaration_list
    .
    (_)* @_between
    .
    [
      (field_declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: [(field_identifier) (operator_name) (destructor_name)] @name)
          (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
          (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        ]) @definition.function
      (declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: (function_declarator
          declarator: [(identifier) (field_identifier) (destructor_name) (operator_name)] @name)) @definition.function
      (function_definition
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: [(field_identifier) (identifier) (destructor_name) (operator_name)] @name)
          (pointer_declarator declarator: (function_declarator declarator: [(field_identifier) (operator_name)] @name))
          (reference_declarator (function_declarator declarator: [(field_identifier) (operator_name)] @name))
        ]) @definition.function
      (template_declaration
        [
          (declaration
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
          (field_declaration
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: (field_identifier) @name)) @definition.function
          (function_definition
            ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
            declarator: (function_declarator declarator: [(identifier) (field_identifier)] @name)) @definition.function
        ])
      (field_declaration type: (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
      (field_declaration type: (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
      (field_declaration type: (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
      (field_declaration type: (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
      (alias_declaration name: (type_identifier) @name) @definition.type
      (type_definition declarator: (type_identifier) @name) @definition.type
    ]
    (#not-match? @_between "^(public|private|protected)$"))) @visibility.public

; Free functions and prototypes. `static` ones, and those in an anonymous
; namespace, are private to their file.
(namespace_definition
  !name
  body: (declaration_list
    [
      (function_definition
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: (identifier) @name)
          (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
          (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
          (reference_declarator (function_declarator declarator: (identifier) @name))
        ]
        (#not-match? @name "^(TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)$")) @definition.function
      (declaration
        ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
        declarator: [
          (function_declarator declarator: (identifier) @name)
          (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
          (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
          (reference_declarator (function_declarator declarator: (identifier) @name))
        ]) @definition.function
    ])) @visibility.private

(function_definition
  (storage_class_specifier) @visibility.private
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (identifier) @name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
    (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
    (reference_declarator (function_declarator declarator: (identifier) @name))
  ]
  (#eq? @visibility.private "static")) @definition.function

(function_definition
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (identifier) @name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
    (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
    (reference_declarator (function_declarator declarator: (identifier) @name))
  ]
  (#not-match? @name "^(TEST|TEST_F|TEST_P|TYPED_TEST|TYPED_TEST_P)$")) @definition.function

(declaration
  (storage_class_specifier) @visibility.private
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (identifier) @name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
    (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
    (reference_declarator (function_declarator declarator: (identifier) @name))
  ]
  (#eq? @visibility.private "static")) @definition.function

(declaration
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (identifier) @name)
    (pointer_declarator declarator: (function_declarator declarator: (identifier) @name))
    (pointer_declarator declarator: (pointer_declarator declarator: (function_declarator declarator: (identifier) @name)))
    (reference_declarator (function_declarator declarator: (identifier) @name))
  ]) @definition.function

; Members defined outside their class: void Monitor::record(...) { ... }.
; The innermost qualifier names the parent (a namespace-qualified free
; function reads as a method of its namespace).
(function_definition
  ([(type_qualifier "const") (type_qualifier "volatile")] @signature . type: (_) @signature)? type: (_)? @signature
  declarator: [
    (function_declarator declarator: (qualified_identifier scope: (namespace_identifier) @parent name: [(identifier) (destructor_name) (operator_name)] @name))
    (pointer_declarator declarator: (function_declarator declarator: (qualified_identifier scope: (namespace_identifier) @parent name: [(identifier) (destructor_name) (operator_name)] @name)))
    (reference_declarator (function_declarator declarator: (qualified_identifier scope: (namespace_identifier) @parent name: [(identifier) (destructor_name) (operator_name)] @name)))
    (function_declarator declarator: (qualified_identifier scope: (template_type name: (type_identifier) @parent) name: [(identifier) (destructor_name) (operator_name)] @name))
    (pointer_declarator declarator: (function_declarator declarator: (qualified_identifier scope: (template_type name: (type_identifier) @parent) name: [(identifier) (destructor_name) (operator_name)] @name)))
    (reference_declarator (function_declarator declarator: (qualified_identifier scope: (template_type name: (type_identifier) @parent) name: [(identifier) (destructor_name) (operator_name)] @name)))
    (function_declarator declarator: (qualified_identifier name: (qualified_identifier scope: (namespace_identifier) @parent name: [(identifier) (destructor_name) (operator_name)] @name)))
    (pointer_declarator declarator: (function_declarator declarator: (qualified_identifier name: (qualified_identifier scope: (namespace_identifier) @parent name: [(identifier) (destructor_name) (operator_name)] @name))))
    (reference_declarator (function_declarator declarator: (qualified_identifier name: (qualified_identifier scope: (namespace_identifier) @parent name: [(identifier) (destructor_name) (operator_name)] @name))))
    (function_declarator declarator: (qualified_identifier name: (qualified_identifier scope: (template_type name: (type_identifier) @parent) name: [(identifier) (destructor_name) (operator_name)] @name)))
    (pointer_declarator declarator: (function_declarator declarator: (qualified_identifier name: (qualified_identifier scope: (template_type name: (type_identifier) @parent) name: [(identifier) (destructor_name) (operator_name)] @name))))
    (reference_declarator (function_declarator declarator: (qualified_identifier name: (qualified_identifier scope: (template_type name: (type_identifier) @parent) name: [(identifier) (destructor_name) (operator_name)] @name))))
  ]) @definition.method

; Classes, structs, unions and enums with a body. Inside a typedef they are the
; typedef's symbol instead (below).
[
  (translation_unit (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (declaration_list (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (template_declaration (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (declaration (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (field_declaration (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (preproc_ifdef (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (preproc_if (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (preproc_else (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
  (preproc_elif (class_specifier name: (type_identifier) @name body: (_)) @definition.class)
]

[
  (translation_unit (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (declaration_list (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (template_declaration (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (declaration (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (field_declaration (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_ifdef (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_if (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_else (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_elif (struct_specifier name: (type_identifier) @name body: (_)) @definition.struct)
]

[
  (translation_unit (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (declaration_list (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (template_declaration (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (declaration (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (field_declaration (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_ifdef (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_if (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_else (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
  (preproc_elif (union_specifier name: (type_identifier) @name body: (_)) @definition.struct)
]

[
  (translation_unit (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (declaration_list (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
  (template_declaration (enum_specifier name: (type_identifier) @name body: (_)) @definition.enum)
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

(alias_declaration
  name: (type_identifier) @name) @definition.type

; Namespaces are one-line symbols (their name), so that they never become the
; parent of what is inside them: a member defined out of class keeps its class
; as parent, as its declaration does.
(namespace_definition
  name: [(namespace_identifier) (nested_namespace_specifier)] @name @definition.namespace)

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
  (#match? @_const "^(const|constexpr)$")) @definition.constant

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
  (#match? @_const "^(const|constexpr)$")) @definition.constant

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
; first, then qualified, template and member calls.
(call_expression function: (identifier) @name) @reference.call
(call_expression function: (qualified_identifier name: (identifier) @name)) @reference.call
(call_expression function: (qualified_identifier name: (qualified_identifier name: (identifier) @name))) @reference.call
(call_expression function: (template_function name: (identifier) @name)) @reference.call
(call_expression function: (qualified_identifier name: (template_function name: (identifier) @name))) @reference.call
(call_expression function: (field_expression field: (field_identifier) @name)) @reference.call
(call_expression function: (field_expression field: (template_method name: (field_identifier) @name))) @reference.call
