from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0002_userprofile_badges_userprofile_last_activity_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='userprofile',
            name='latitude',
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='userprofile',
            name='longitude',
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                max_digits=9,
                null=True,
            ),
        ),
    ]
