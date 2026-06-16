from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("rust", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="rustdistribution",
            options={
                "default_related_name": "%(app_label)s_%(model_name)s",
                "permissions": [
                    (
                        "manage_roles_rustdistribution",
                        "Can manage roles on rust distributions",
                    ),
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="rustremote",
            options={
                "default_related_name": "%(app_label)s_%(model_name)s",
                "permissions": [
                    ("manage_roles_rustremote", "Can manage roles on rust remotes"),
                ],
            },
        ),
        migrations.AlterModelOptions(
            name="rustrepository",
            options={
                "default_related_name": "%(app_label)s_%(model_name)s",
                "permissions": [
                    ("modify_rustrepository", "Can modify content of the repository"),
                    (
                        "manage_roles_rustrepository",
                        "Can manage roles on rust repositories",
                    ),
                ],
            },
        ),
    ]
