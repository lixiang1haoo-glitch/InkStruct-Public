# Contributing to InkStruct

## Clone and set up

Clone the repository together with the pinned Make Me a Hanzi data:

```powershell
git clone --recurse-submodules <repository-url>
cd InkStruct
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,dev]"
```

For an existing clone, initialize or repair the submodule with:

```powershell
git submodule sync --recursive
git submodule update --init --recursive
```

## Branch and review workflow

1. Update `main`, then create a short-lived branch such as `feature/<topic>`,
   `fix/<topic>`, or `docs/<topic>`.
2. Keep commits focused and explain the behavior changed by each commit.
3. Before review, run the checks relevant to the change:

   ```powershell
   .\.venv\Scripts\python.exe -m pytest
   .\.venv\Scripts\ruff.exe check src tests scripts packaging
   ```

4. In the pull request, describe the problem, resulting behavior, validation,
   and any data or compatibility implications.

## Repository boundaries

Do not commit user samples, generated profiles, model weights, databases, local
environment files, or generated output. The repository `.gitignore` excludes
the standard locations for these files: `data/`, `artifacts/`, `profiles/`,
`outputs/`, `release/`, `.venv/`, and `.env*`.

Keep Make Me a Hanzi changes as a submodule pointer update. When changing that
pointer, include the upstream commit and the rebuilt structure report in the
review description. Third-party data and user data have licenses and privacy
requirements separate from the InkStruct MIT license.

Generated trajectories must preserve the project invariants: standard stroke
count, continuous stroke order, valid standard stroke IDs, finite normalized
coordinates, bounded pressure, and monotonic timestamps.
