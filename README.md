# birthday-party
Distributed hash collision search dashboard

## Local Development

### Installation

1. Clone the repository
2. Install dependencies:
   ```bash
   pip install -e .
   ```

### Database Setup

Initialize the database (only needed once):
```bash
python init_test_db.py
```

This creates `birthdayparty.db` with the necessary tables and test users.

### Running the Server

Start the development server:
```bash
python server.py
```

The server will run on `http://localhost:8080` by default.
