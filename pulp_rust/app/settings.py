import socket

CRATES_IO_API_HOSTNAME = "https://" + socket.getfqdn()

DRF_ACCESS_POLICY = {
    "dynaconf_merge_unique": True,
    "reusable_conditions": ["pulp_rust.app.global_access_conditions"],
}
