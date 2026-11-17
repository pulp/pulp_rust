from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rust', '0005_rustcargotoken_actions_rustcargotoken_distributions'),
    ]

    operations = [
        migrations.AddField(
            model_name='rustdistribution',
            name='cargo_auth_required',
            field=models.BooleanField(default=False),
        ),
    ]
