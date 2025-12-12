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

To init/reset the database and start fresh:
```bash
python reset_db.py
```

This will delete the existing database and create a new one with test users.

### Running the Server

Start the development server:
```bash
python server.py
```

The server will run on `http://localhost:8080` by default.
