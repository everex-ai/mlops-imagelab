# Generated for reviewer role addition

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("organizations", "0002_invitation_sent_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="membership",
            name="role",
            field=models.CharField(
                choices=[
                    ("worker", "Worker"),
                    ("reviewer", "Reviewer"),
                    ("supervisor", "Supervisor"),
                    ("maintainer", "Maintainer"),
                    ("owner", "Owner"),
                ],
                max_length=16,
            ),
        ),
    ]
