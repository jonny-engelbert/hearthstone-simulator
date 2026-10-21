# Project workflow

Keep requirements, code, tests and supporting artifacts in this project folder.
Use the single current catalog, schema and manifest; preserve versions in Git.
Update CHANGELOG.txt concisely. Follow docs/requirements.txt and docs/test-plan.txt.

After completing authorized project changes:
- Work on a codex/ feature branch; never push directly to main.
- Run catalog/manifest checks, formatting, and the full test suite.
- Commit the completed changes, then run python3 tools/publish.py to repeat checks
  and push the committed branch to origin. Install requirements-dev.txt first.
- Open or update a pull request, attach it to this chat, and verify GitHub CI.
- Report the commit, pull request, and CI outcome, including any publishing failure.
- Merge a pull request only when the user asks to merge it. Do not enable automatic
  merging, commit unfinished changes, or add background file-watching publishers.

CI validates every push and pull request. Main requires the aggregate CI check.
For a larger manual CI run, choose random_games=100 in the CI workflow dispatcher.
