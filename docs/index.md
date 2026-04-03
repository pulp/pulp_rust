# Welcome to Pulp Rust

The `rust` plugin extends [pulpcore](site:pulpcore/) to support hosting Rust/Cargo package registries. This plugin is a part of the [Pulp Project](site:/), and assumes some familiarity with the [pulpcore documentation](site:pulpcore/).

!!! warning "Tech Preview"
    This plugin is currently in **tech preview**. APIs, behaviors, and data models are subject to change, including breaking changes, without prior notice.

If you are just getting started, we recommend getting to know the [basic workflows](site:pulp_rust/docs/user/guides/pull-through-cache/).

See the [REST API documentation](site:pulp_rust/restapi/) for detailed endpoint reference.

## Features

- [Use Pulp as a pull-through cache](site:pulp_rust/docs/user/guides/pull-through-cache/) for crates.io or any Cargo sparse registry
- [Host a private Cargo registry](site:pulp_rust/docs/user/guides/private-registry/) for internal crates
- Publish crates with `cargo publish` and manage them with `cargo yank`
- Implements the [Cargo sparse registry protocol](https://doc.rust-lang.org/cargo/reference/registry-index.html#sparse-index) for compatibility with standard Cargo tooling
- Download crates on-demand to reduce disk usage
- Every operation creates a restorable snapshot with Versioned Repositories
- Host content either locally or on S3/Azure/GCP
- De-duplication of all saved content
