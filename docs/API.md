# Birthday Party HTTP API

This document describes the HTTP API for the Birthday Party server.

## Base URL

```
http://localhost:8080
```

## Endpoints

### GET /

Returns an HTML dashboard displaying statistics and information.

**Response:** `text/html`

**Example:**
```bash
curl http://localhost:8080/
```

---

### POST /submit_work

Submit distinguished points found during search.

**Content-Type:** `application/json`

**Request Body:**
```json
{
  "username": "string",
  "usertoken": "string",
  "results": [
    {
      "start": "hex_string",
      "dp": "hex_string"
    },
    ...
  ]
}
```

**Fields:**
- `username` (string, required): Username for authentication
- `usertoken` (string, required): Authentication token
- `results` (array, required): Array of results, each containing:
  - `start` (string, required): Hex-encoded starting point
  - `dp` (string, required): Hex-encoded distinguished point

**Success Response (200):**
```json
{
  "status": "accepted N results in X.XXms"
}
```

**Error Responses:**

400 Bad Request:
```json
{
  "status": "bad request"
}
```
```json
{
  "status": "invalid result data format"
}
```
```json
{
  "status": "bad hash length"
}
```

401 Unauthorized:
```json
{
  "status": "bad username and/or usertoken"
}
```

**Example:**
```bash
curl -X POST http://localhost:8080/submit_work \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "usertoken": "secret123",
    "results": [
      {
        "start": "1234567890abcdef",
        "dp": "0000567890abcdef"
      }
    ]
  }'
```
