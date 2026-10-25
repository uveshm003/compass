; The grammar has almost no field names, so names and bodies are matched by
; node type. Annotations live inside `modifiers`.

; Types: interface and enum first, so the generic class pattern does not win.
(class_declaration
  (modifiers)? @visibility
  "interface"
  (type_identifier) @name
  (class_body)? @body) @definition.interface

(class_declaration
  (modifiers)? @visibility
  "enum"
  (type_identifier) @name
  (enum_class_body)? @body) @definition.enum

(class_declaration
  (modifiers)? @visibility
  (type_identifier) @name
  (class_body)? @body) @definition.class

(object_declaration
  (modifiers)? @visibility
  (type_identifier) @name
  (class_body)? @body) @definition.class

(companion_object
  (modifiers)? @visibility
  (type_identifier) @name
  (class_body)? @body) @definition.class

(type_alias
  (modifiers)? @visibility
  (type_identifier) @name) @definition.type

; Functions; those inside classes, interfaces and objects become methods. The
; signature starts at the type parameters or the receiver of an extension:
; "List<Reading>.alarms(threshold: Double): List<Reading>".
(function_declaration
  (modifiers)? @visibility
  (type_parameters) @signature
  (simple_identifier) @name
  (function_body)? @body) @definition.function

(function_declaration
  (modifiers)? @visibility
  receiver: (receiver_type) @signature
  (simple_identifier) @name
  (function_body)? @body) @definition.function

(function_declaration
  (modifiers)? @visibility
  (simple_identifier) @name
  (function_body)? @body) @definition.function

(secondary_constructor
  (modifiers)? @visibility
  "constructor" @name
  (statements)? @body) @definition.method

; `const val` anywhere (top level, objects, companions), then every other
; top-level property.
(property_declaration
  (modifiers
    (property_modifier) @_const) @visibility
  (variable_declaration
    (simple_identifier) @name)
  (#eq? @_const "const")) @definition.constant

(source_file
  (property_declaration
    (modifiers)? @visibility
    (variable_declaration
      (simple_identifier) @name)) @definition.variable)

; References: call sites, for callers_of. Constructor calls look like plain
; calls (Reading(...)). Matched by name only.
(call_expression
  (simple_identifier) @name) @reference.call

(call_expression
  (navigation_expression
    (navigation_suffix
      (simple_identifier) @name))) @reference.call

; Function references (::isAlarm, Reading::isAlarm) pass a function to be called later.
(callable_reference
  (simple_identifier) @name .) @reference.call
