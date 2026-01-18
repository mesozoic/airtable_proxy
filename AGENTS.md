# Project overview

- Read all project information and contributor guidelines in @README.md
- Maintain the project todo list in @TODO.md
- Try to infer idioms and patterns from existing code.
- Update this file with notes as you learn about the team's preferred style.
- Do not give yourself credit in commit messages.

# Application structure

- Avoid overcomplication or YAGNI layers of abstraction.

# Testing best practices

- Use `mypy && pytest` for testing
- Use `pre-commit run` for formatting after tests pass
- Put source in `src/airtable_proxy/` and tests in `tests/`
- Tests for `src/airtable_proxy/module/submodule.py` go in `tests/test_module_submodule.py`
- Use outside-in test driven development.
- Follow red-green-refactor. Don't clean up code before it works.
- Always ask for confirmation after changing tests, before implementation.
- Do not use type annotations in test files. It's not necessary.
- Use `@patch` decorator instead of wrapping entire tests in `with patch(...)`
- Import the module under test; don't import every class/function from it.
