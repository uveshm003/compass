(import_statement
  name: (dotted_name) @import)

(import_statement
  name: (aliased_import
    name: (dotted_name) @import))

; `from pkg import models` targets pkg.models, which resolves to pkg/models.py
; when that module exists and to the package otherwise.
(import_from_statement
  module_name: (_) @import
  name: (dotted_name) @import.member)

(import_from_statement
  module_name: (_) @import
  name: (aliased_import
    name: (dotted_name) @import.member))

(import_from_statement
  module_name: (_) @import
  (wildcard_import))
