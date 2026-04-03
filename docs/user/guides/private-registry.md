# Host a Private Cargo Registry

This guide walks you through setting up Pulp as a private Cargo registry for hosting internal
crates. This is useful for organizations that need to distribute proprietary or internal-only
Rust packages.

## Create a Repository

```bash
pulp rust repository create --name my-crates
```

## Create a Distribution

A distribution makes the repository's content available to Cargo over HTTP. Set `--allow-uploads`
to enable publishing crates via `cargo publish`.

```bash
pulp rust distribution create \
    --name my-crates \
    --base-path my-crates \
    --repository my-crates \
    --allow-uploads
```

Your private registry is now served at `http://<pulp-host>/pulp/cargo/my-crates/`.

## Configure Cargo

Add the private registry to your Cargo configuration. Create or edit `~/.cargo/config.toml`:

```toml
[registries.my-crates]
index = "sparse+http://<pulp-host>/pulp/cargo/my-crates/"
```

## Authentication

State-changing operations (publishing, yanking, and unyanking) require an authorization token.
Configure the token for your registry in `~/.cargo/credentials.toml`:

```toml
[registries.my-crates]
token = "i_understand_that_pulp_rust_does_not_support_proper_auth_yet"
```

Alternatively, you can pass the token on the command line:

```bash
cargo publish --registry my-crates --token "i_understand_that_pulp_rust_does_not_support_proper_auth_yet"
```

!!! warning
    This is a temporary stub token. Proper token-based authentication is planned for a future
    release. The stub token exists to ensure that the authentication workflow is exercised and that
    state-changing operations are not completely open.

Read-only operations (downloading crates, browsing the index) do not require a token.

## Publish a Crate

Once the registry is configured and a distribution with `--allow-uploads` exists, you can publish
crates using standard Cargo tooling:

```bash
cargo publish --registry my-crates
```

This uploads the crate to Pulp, which creates the artifact, content metadata, and a new repository
version. The crate is immediately available for download through the distribution.

Publishing the same crate version twice is rejected — crate versions are immutable, consistent
with crates.io behavior.

## Yank and Unyank

Yanking marks a crate version as unavailable for new dependency resolution, while still allowing
existing projects that already depend on it to continue downloading it. This matches the
[crates.io yank semantics](https://doc.rust-lang.org/cargo/reference/publishing.html#cargo-yank).

```bash
# Yank a version
cargo yank --registry my-crates --version 1.0.0 my-crate

# Unyank a version
cargo yank --registry my-crates --version 1.0.0 --undo my-crate
```

### Using the Private Registry as a Dependency Source

To depend on crates from your private registry, specify the registry in your `Cargo.toml`:

```toml
[dependencies]
my-internal-lib = { version = "1.0", registry = "my-crates" }
```

### Setting the Default Registry

You can set your private registry as the default for `cargo publish` and other registry commands
so you don't need to pass `--registry` every time:

```toml
[registry]
default = "my-crates"
```

This affects commands like `cargo publish`, `cargo yank`, and `cargo owner`. It does **not**
change where dependencies are resolved from — that is controlled by source replacement (below).

!!! tip
    Setting a default registry is recommended for organizations with private crates. Without it,
    running `cargo publish` without `--registry` will publish to crates.io by default, which could
    accidentally leak proprietary code to the public registry.

### Replacing crates.io Entirely

If you want all crate lookups to go through your private registry (for example, in an air-gapped
environment), you can replace the default source:

```toml
[source.crates-io]
replace-with = "my-crates"

[source.my-crates]
registry = "sparse+http://<pulp-host>/pulp/cargo/my-crates/"
```

This redirects all dependency resolution — including transitive dependencies — through your
private registry. Any crate not present in the registry will fail to resolve.

## Combining with Pull-Through Caching

If you need both private crates and public crates.io dependencies, we recommend keeping them as
**separate registries** rather than mixing them into one. This avoids
[dependency confusion](https://medium.com/@alex.birsan/dependency-confusion-4a5d60fec610) attacks,
where a malicious package on a public registry could impersonate a private dependency.

```bash
# Set up a separate pull-through cache for crates.io
pulp rust remote create --name crates-io --url "sparse+https://index.crates.io/" --policy on_demand
pulp rust repository create --name crates-io-cache --remote crates-io --retain-repo-versions 1
pulp rust distribution create \
    --name crates-io-cache \
    --base-path crates-io-cache \
    --repository crates-io-cache \
    --remote crates-io
```

Then configure Cargo to use both registries, with crates.io going through the cache and private
crates resolved from your private registry:

```toml
[registries.my-crates]
index = "sparse+http://<pulp-host>/pulp/cargo/my-crates/"

[source.crates-io]
replace-with = "crates-io-cache"

[source.crates-io-cache]
registry = "sparse+http://<pulp-host>/pulp/cargo/crates-io-cache/"
```

```toml
[dependencies]
serde = "1.0"                                              # resolved from crates-io-cache
my-internal-lib = { version = "1.0", registry = "my-crates" }  # resolved from private registry
```

!!! warning
    Avoid adding a public remote (such as crates.io) to a private registry's distribution. Mixing
    public and private packages in a single registry index creates a risk of dependency confusion
    attacks, where an attacker publishes a crate on the public registry with the same name as one
    of your private crates.

## Further Reading

- [Cargo registries configuration](https://doc.rust-lang.org/cargo/reference/registries.html) -- configuring alternate registries in Cargo
- [Cargo source replacement](https://doc.rust-lang.org/cargo/reference/source-replacement.html) -- replacing crates.io with an alternate source
- [Cargo config reference](https://doc.rust-lang.org/cargo/reference/config.html) -- full reference for `.cargo/config.toml`
- [Specifying dependencies](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html#specifying-dependencies-from-other-registries) -- using dependencies from alternate registries
