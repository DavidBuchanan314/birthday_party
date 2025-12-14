# birthday-party
Distributed hash collision search dashboard

## Local Development

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   python3 -m pip install -e .
   ```
3. (Optional) Install dev dependencies:
   ```bash
   python3 -m ppip install -e ".[dev]"
   ```
4. (Optional) Set up pre-commit hooks to auto-format on commit:
   ```bash
   pre-commit install
   ```

### Creating Users

To create a new user with an auto-generated UUIDv4 password:
```bash
python3 -m birthday_party.create_user <username>
```

To create a user with a specific password:
```bash
python3 -m birthday_party.create_user <username> --password <password>
```

Example:
```bash
python3 -m birthday_party.create_user alice
# Output: Generated password: 550e8400-e29b-41d4-a716-446655440000
```

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
