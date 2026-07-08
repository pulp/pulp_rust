Added per-user Cargo token authentication for Cargo API endpoints (publish, yank, unyank, /me),
replacing the hardcoded stub token. Tokens are created via the REST API and sent by Cargo
in the `Authorization` header.
