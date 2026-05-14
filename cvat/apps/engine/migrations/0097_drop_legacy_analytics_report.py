from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0096_alter_task_dimension"),
    ]

    operations = [
        migrations.RunSQL(
            sql="DROP TABLE IF EXISTS analytics_report_analyticsreport CASCADE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
