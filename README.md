# pulp-rust

A Pulp plugin to support hosting your own Rust/Cargo package registry.

> **Tech Preview**: This project is currently in tech preview. APIs, behaviors, and data models are subject to change, including breaking changes, without prior notice.

## Features

- Use Pulp as a pull-through cache for crates.io or any Cargo sparse registry
- Host a private Cargo registry for internal crates
- Implements the [Cargo sparse registry protocol](https://doc.rust-lang.org/cargo/reference/registry-index.html#sparse-index) for compatibility with standard Cargo tooling
- Download crates on-demand to reduce disk usage
- Every operation creates a restorable snapshot with Versioned Repositories
- Host content either locally or on S3/Azure/GCP
- De-duplication of all saved content

For more information, please see the [documentation](docs/index.md) or the [Pulp project page](https://pulpproject.org/).


How to File an Issue
--------------------

File through this project's GitHub issues and appropriate labels.

> **WARNING** Is this security related? If so, please follow the [Security Disclosures](https://docs.pulpproject.org/pulpcore/bugs-features.html#security-bugs) procedure.
