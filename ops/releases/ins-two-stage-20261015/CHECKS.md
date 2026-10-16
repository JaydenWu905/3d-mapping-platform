# Release-preservation checks

No GLIM/MrHash execution, environment installation, upgrade or native compilation
was performed while preserving this release.

Passed:

- 20 lightweight unit tests: test_ins_run_modes, test_surface_input,
  test_mesh_preview. Tests use isolated fixtures; no real algorithm is invoked.
- `npm run typecheck --prefix frontend`.
- Python AST parse of 49 platform/operational source files and the deployed
  MrHash reader/entrypoint sources, without importing algorithm modules.
- `bash -n ops/platform.sh ops/glim-child.sh`.
- HTTP 200 from backend health, frontend, and both registered previews of each
  of the three preserved Jobs. GLB response SHA matches each manifest.
- All ordinary files in the three Job directories unchanged: 93 / 106 / 108.
- All original MrHash tracked working-tree contents and the 32 backed-up
  untracked source/config files retain their pre-preservation SHA. In the
  platform, only README/.gitignore were edited from the pre-existing tracked
  worktree; the 42 backed-up untracked files remain unchanged.
- Installed MrHash native-extension SHA unchanged.
- Explicit staged-file type/size exclusions and secret-pattern review.

Known source-format note: raw `git diff --cached --check` reports three inherited
trailing spaces in GLIM JSON comments. Those templates are retained byte-for-byte
for correspondence with accepted configuration; no algorithm setting changed.
No generated logs, binary outputs or runtime validation files are committed.
Full local machine-readable checks are retained with the source-only backup.
