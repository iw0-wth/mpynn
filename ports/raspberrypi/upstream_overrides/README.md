# Read-only upstream dependency policy

Do not modify source files under mpynn/lib for port changes. Adaptations belong
here, in port C bridges, or in ports/raspberrypi/modules.

- circle/: seventeen allowlisted Circle-relative replacement files. build_circle.py
  hashes them, rejects links/overlaps and copies them into its owned build stage.
  Port C++ glue includes these headers before upstream Circle headers.
- micropython/extmod/modsocket.c: built instead of the upstream socket source,
  never in addition to it.
- micropython/tools/makemanifest.py: port-owned manifest generation adaptation;
  tools/makemanifest.py runs it with upstream imports and bytecode writing disabled.
- ../modules/requests: frozen instead of the upstream requests package. Default
  HTTPS policy stays CERT_NONE; optional supplied SSLContext is preserved.

restored-sources.json records the restored bytes of the twelve known modified
vendor files. test_upstream_readonly.py detects future accidental edits. This is
not proof that the whole lib tree matches a particular upstream Git commit.
Known edits were restored by targeted inverse operations because this checkout
has no Git metadata. Existing unrelated content was not replaced.

Keep upstream licence headers in adapted copies. When upgrading dependencies,
review differences and update both the adapters and restored baseline deliberately.
