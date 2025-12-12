# birthday-party
Distributed hash collision search dashboard

## Local Development

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -e .
   ```
3. (Optional) Install dev dependencies:
   ```bash
   pip install -e ".[dev]"
   ```
4. (Optional) Set up pre-commit hooks to auto-format on commit:
   ```bash
   pre-commit install
   ```

### Database Setup

To init/reset the database and start fresh:
```bash
python3 -m birthday_party.reset_db
```

This will delete the existing database and create a new one with test users.

### Running the Server

Start the development server:
```bash
python3 -m birthday_party.server
```

The server will run on `http://localhost:8080` by default.

### Testing

Run the integration test suite:
```bash
pytest
```

Run with verbose output:
```bash
pytest -v
```

Run a specific test file:
```bash
pytest tests/test_server.py
```

### Code Formatting

The project uses Ruff for formatting (with tabs for indentation).

If you installed pre-commit hooks, code will be automatically formatted on each commit.

Manual formatting:
```bash
ruff format .
```

Check for linting issues:
```bash
ruff check .
```
