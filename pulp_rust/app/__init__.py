from pulpcore.plugin import PulpPluginAppConfig


class PulpRustPluginAppConfig(PulpPluginAppConfig):
    """Entry point for the rust plugin."""

    name = "pulp_rust.app"
    label = "rust"
    version = "0.0.0.dev"
    python_package_name = "pulp_rust"
    domain_compatible = True
