from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('food_management', '0005_donationrequest_requested_by'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryitem',
            name='barcode',
            field=models.CharField(blank=True, db_index=True, max_length=128),
        ),
        migrations.CreateModel(
            name='CategoryConfig',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(max_length=100, unique=True)),
                ('critical_days', models.PositiveIntegerField(default=3)),
                ('high_days', models.PositiveIntegerField(default=7)),
                ('medium_days', models.PositiveIntegerField(default=30)),
                ('shelf_life_days', models.PositiveIntegerField(blank=True, null=True)),
                ('default_unit', models.CharField(default='kg', max_length=30)),
                ('is_active', models.BooleanField(default=True)),
            ],
            options={'ordering': ['category']},
        ),
        migrations.CreateModel(
            name='InAppNotification',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=200)),
                ('message', models.TextField()),
                ('link', models.CharField(blank=True, max_length=255)),
                ('notification_type', models.CharField(default='info', max_length=50)),
                ('is_read', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='notifications', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='inappnotification',
            index=models.Index(fields=['user', 'is_read', '-created_at'], name='food_manage_user_id_582191_idx'),
        ),
    ]
