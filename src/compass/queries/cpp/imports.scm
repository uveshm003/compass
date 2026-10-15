; #include "local.h" (quotes stripped) and #include <system.h> (brackets kept,
; so system headers read as they are written: importers_of("<fmt/core.h>")).
(preproc_include
  path: (string_literal) @import)

(preproc_include
  path: (system_lib_string) @import)
