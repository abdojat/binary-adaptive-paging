# Cleanup evidence

`before.sha256.json` records the 317 tracked working-tree files before cleanup at `a56b720`. `after.sha256.json` records those same original files at their final locations, including the three locally retained, now-untracked binaries. Those binaries are packaging exceptions and are not required in a clean checkout. `.gitignore` is the only original file whose contents intentionally changed. Five Markdown files moved byte-for-byte into `docs/`.

`inventory.json` provides original/final paths, byte sizes, SHA-256 and row counts for every original CSV. This inventory intentionally excludes newly authored cleanup files and the two user-supplied untracked reports. It is an evidence-freeze inventory, not a complete listing of the new working tree.

`validation.log` records the actual full validator invocation with ten fresh processes per native program. Temporary paths in the log no longer exist. Fresh timing contrasts printed there are smoke-test output, not replacements for archived research findings.

Raw byte hashes are sensitive to Git newline conversion: 223 original files have CRLF/LF differences between this checkout and their Git blobs. `git-blobs.sha256.json` separately records original `HEAD` blob hashes. The validator accepts only an exact match to either recorded representation, and reports how many use the blob representation. All 223 differences were checked to be newline-only. The before/after manifests retain exact local bytes; no evidence is normalized in place. A clone with `core.autocrlf=false` can use the blob hashes. Hashes verify identity, not authorship or scientific truth.
