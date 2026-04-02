# Host a Private Cargo Registry

This guide walks you through setting up Pulp as a private Cargo registry for hosting internal
crates. This is useful for organizations that need to distribute proprietary or internal-only
Rust packages.

!!! note
    Package publishing support (`cargo publish`) is not yet available but is planned for an
    upcoming release. In the meantime, content can be uploaded through the Pulp REST API.

## Create a Repository

```bash
pulp rust repository create --name my-crates
```

## Create a Distribution

A distribution makes the repository's content available to Cargo over HTTP.

```bash
pulp rust distribution create \
    --name my-crates \
    --base-path my-crates \
    --repository my-crates
```

Your private registry is now served at `http://<pulp-host>/pulp/cargo/my-crates/`.

## Configure Cargo

Add the private registry to your Cargo configuration. Create or edit `~/.cargo/config.toml`:

```toml
[registries.my-crates]
index = "sparse+http://<pulp-host>/pulp/cargo/my-crates/"
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
