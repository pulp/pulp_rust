# Authentication & Authorization

Pulp Rust uses per-user API tokens for Cargo protocol endpoints (publish, yank, unyank) and
Pulp's standard RBAC system for controlling access to repositories, remotes, and distributions.

## Cargo Token Authentication

### Creating a Token

Create a token via the Pulp REST API using your Pulp credentials:

```bash
http POST http://<pulp-host>/pulp/api/v3/cargo/tokens/ \
    -a admin:password \
    name="my-laptop"
```

The response includes the token value (prefixed with `crg_`). This is shown **once** -- it
cannot be retrieved again. Store it securely.

### Using with Cargo

Pass the token to Cargo via `cargo login`:

```bash
cargo login --registry my-crates
# Paste the crg_... token when prompted
```

Or set it directly in `~/.cargo/credentials.toml`:

```toml
[registries.my-crates]
token = "crg_..."
```

Cargo sends the token automatically on state-changing operations (publish, yank, unyank).
Read-only operations (downloading crates, browsing the index) do not require a token.

### Managing Tokens

```bash
# List your tokens (token values are not shown)
http GET http://<pulp-host>/pulp/api/v3/cargo/tokens/ -a user:password

# Revoke a token
http DELETE http://<pulp-host>/pulp/api/v3/cargo/tokens/<token-uuid>/ -a user:password
```

Users can only see and revoke their own tokens.

## Distribution-Scoped Permissions

Access to publish and yank is controlled per-distribution using Pulp's RBAC system. A user
needs the appropriate role on a distribution before they can publish or yank crates through it.

### Roles

| Role | Permissions |
|------|-------------|
| `rust.rustdistribution_owner` | Full control: view, change, delete, manage roles, publish, yank |
| `rust.rustdistribution_publisher` | Publish crates and yank/unyank versions |
| `rust.rustdistribution_viewer` | View the distribution |

The user who creates a distribution automatically receives the `owner` role on it.

### Granting Access

Grant a user permission to publish to a specific distribution:

```bash
http POST http://<pulp-host>/pulp/api/v3/distributions/rust/rust/<uuid>/add_role/ \
    -a admin:password \
    role="rust.rustdistribution_publisher" \
    users:='["alice"]'
```

Alice can now publish and yank crates on that distribution using her Cargo token.

## Differences from crates.io

| Feature | crates.io | Pulp Rust |
|---------|-----------|-----------|
| Access scope | Per-crate ownership | Per-distribution |
| Owner management | `cargo owner --add` | Pulp REST API role assignment |
| Token creation | Web UI at crates.io | Pulp REST API |
| Per-crate ownership | Yes (user and team owners) | Not supported (planned) |
| Token scoping | Scoped to endpoints/crates | Not yet supported |

!!! warning "No per-crate ownership"
    Pulp Rust currently controls access at the distribution level, not per-crate. Any user with
    the `publisher` role on a distribution can publish any crate name to it. Per-crate ownership
    (where only the crate's owner can publish new versions) is planned for a future release.
