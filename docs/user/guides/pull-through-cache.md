# Use Pulp as a Pull-Through Cache

This guide walks you through setting up Pulp as a pull-through cache for an upstream Cargo registry
such as [crates.io](https://crates.io). Cargo will fetch crates through Pulp, which transparently
downloads and stores them on first access. Subsequent requests are served directly from Pulp's
storage backend.

## Create a Remote

A remote tells Pulp where to fetch crates from. The URL should point to the sparse index of
the upstream registry.

```bash
pulp rust remote create --name crates-io --url "sparse+https://index.crates.io/" --policy on_demand
```

The `--policy` flag controls how content is stored:

| Policy      | Behavior                                                                                    |
|-------------|---------------------------------------------------------------------------------------------|
| `on_demand` | Downloads and caches crate files on first request. Metadata is saved to the Pulp database.  |
| `streamed`  | Streams crate files to the client without saving them locally.                              |

For a pull-through cache, `on_demand` is recommended so that crates are retained for future
requests. `streamed` is primarily useful in cases where you want a proxy in between clients and
the public registry for e.g. access control - which is not so common in the Rust ecosystem.

## Create a Repository

Repositories store and organize content in Pulp. When using pull-through caching, crates are
automatically added to the repository as they are downloaded.

```bash
pulp rust repository create --name crates-io-cache --remote crates-io --retain-repo-versions 1
```

!!! tip
    Setting `--retain-repo-versions 1` is recommended for pull-through caches. Each new crate
    download creates a new repository version, and without this setting the number of versions
    will grow unboundedly.

## Create a Distribution

A distribution makes the repository available to Cargo over HTTP. The `--base-path` determines the
URL path where the registry is served.

```bash
pulp rust distribution create \
    --name crates-io-cache \
    --base-path crates-io-cache \
    --repository crates-io-cache \
    --remote crates-io
```

!!! note
    The remote must be set on both the repository and the distribution. The distribution's remote
    controls the proxy fallback for the sparse index, while the repository's remote is used for
    pull-through content storage.

Your registry is now available at `http://<pulp-host>/pulp/cargo/crates-io-cache/`.

## Configure Cargo

To use your Pulp instance as a registry, add it to your Cargo configuration. Create or edit
`~/.cargo/config.toml`:

```toml
[registries.pulp]
index = "sparse+http://<pulp-host>/pulp/cargo/crates-io-cache/"

[source.crates-io]
replace-with = "pulp"

[source.pulp]
registry = "pulp"
```

This tells Cargo to route all crate downloads through Pulp instead of directly to crates.io.

!!! tip
    You can also set this per-project by placing a `.cargo/config.toml` file in your project root.

Now any `cargo build`, `cargo add`, or `cargo install` command will fetch crates through Pulp:

```bash
cargo add serde --features derive
cargo build
```

The first time a crate is requested, Pulp fetches it from the upstream registry and caches it
locally. All subsequent requests for the same crate version are served from Pulp's storage backend.

## Verify Cached Content

You can inspect what content has been cached in Pulp:

```bash
# List cached crates
pulp rust content list --limit 10

# Check repository versions
pulp rust repository version list --repository crates-io-cache
```

## Further Reading

- [Cargo registries configuration](https://doc.rust-lang.org/cargo/reference/registries.html) -- configuring alternate registries in Cargo
- [Cargo source replacement](https://doc.rust-lang.org/cargo/reference/source-replacement.html) -- replacing crates.io with an alternate source
- [Cargo config reference](https://doc.rust-lang.org/cargo/reference/config.html) -- full reference for `.cargo/config.toml`
