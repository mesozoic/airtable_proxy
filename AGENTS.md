# Project overview

- Read all project information and contributor guidelines in @README.md
- Maintain the project todo list in @TODO.md
- Try to infer idioms and patterns from existing code.

# Testing best practices

- Use `mypy && pytest` for testing
- Use `pre-commit run` for formatting after tests pass
- Put source in `src/airtable_proxy/` and tests in `tests/`
- Tests for `src/airtable_proxy/module/submodule.py` go in `tests/test_module_submodule.py`
- Use outside-in test driven development.
- Follow red-green-refactor. Don't clean up code before it works.
- Do not use type annotations in test files. It's not necessary.
