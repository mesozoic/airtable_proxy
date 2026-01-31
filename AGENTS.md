# Agent instructions

- Read all project information and contributor guidelines in @README.md
- Maintain the project todo list in @TODO.md
- Try to infer idioms and patterns from existing code.
- Update this file with notes as you learn about the team's preferred style.
- Do not give yourself credit in commit messages.

# Common commands

- Use `mypy --strict && pytest --cov` for testing
- Use `pre-commit run` for formatting after tests pass
- Run integration tests with `dotenv -f tmp/integration.sh run -- pytest -k integration`

# Application structure

- Avoid overcomplication or YAGNI layers of abstraction.
- Use type annotations everywhere.

# Testing best practices

- Put source in `src/airtable_proxy/` and tests in `tests/`
- Tests for `src/airtable_proxy/module/submodule.py` go in:
    - `tests/test_module_submodule.py` for unit tests
    - `tests/integration/itest_module_submodule.py` for integration tests
- Integration tests for `src/airtable_proxy/module/submodule.py` go in `tests/integration/itest_module_submodule.py`
- Use test driven development and red-green-refactor.
    - Write tests first, ask for review, then make the tests pass.
    - Always ask for confirmation when writing or changing tests.
    - Don't refactor or clean up code until implementation passes tests.
    - Don't remove tests when refactoring or cleaning up your code.
- Do not use type annotations in test files. It's not necessary.
- Use `@patch` decorator instead of wrapping entire tests in `with patch(...)`
- Import the module under test; don't import every class/function from it.

# Stylistic preferences

- Never use one-line docstrings; always put `"""` on its own line.
- Avoid massive try/except or try/finally blocks.
-
