; Only file-level `use` declarations: a `use super::*` inside an inline
; `mod tests` refers to the file itself, not to another file.
(source_file
  (use_declaration
    argument: [(scoped_identifier) (identifier) (crate) (self) (super)] @import))

(source_file
  (use_declaration
    argument: (use_as_clause
      path: (_) @import)))

(source_file
  (use_declaration
    argument: (use_wildcard
      (_) @import)))

; `use crate::t::{x, y::z}` targets crate::t::x and crate::t::y::z.
(source_file
  (use_declaration
    argument: (scoped_use_list
      path: (_) @import
      list: (use_list
        [(identifier) (scoped_identifier)] @import.member))))

(source_file
  (use_declaration
    argument: (scoped_use_list
      path: (_) @import
      list: (use_list
        (use_as_clause
          path: (_) @import.member)))))

(source_file
  (extern_crate_declaration
    name: (identifier) @import))
