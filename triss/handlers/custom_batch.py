"""
triss.handlers.custom_batch
============================
/custombatch shares almost all of its logic with /batch (open-ended
capture, /done, /cancelbatch) — the only real difference is that a plain
batch stores everything between the first and last message, while a
custom batch stores only the messages explicitly sent during the
session. Both are driven by the *same* session-kind-aware capture and
finalize logic, so to avoid duplicating that logic across two files
(and risking it drifting out of sync), all of it lives in
`triss.handlers.batch`, including the `/custombatch` command itself.

This module is kept as a real file (per the requested project layout)
and imported by `triss.bot` for consistency, but intentionally contains
no separate handlers of its own.
"""
