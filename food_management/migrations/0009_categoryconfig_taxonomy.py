from django.db import migrations, models


DEFAULT_CATEGORIES = [
    ('dairy', 'perishable', 'Refrigerated; keep at 0-4 C', 10, 'litres'),
    ('bakery', 'highly_perishable', 'Cool, dry bakery rack', 3, 'kg'),
    ('produce', 'highly_perishable', 'Refrigerated produce drawer', 7, 'kg'),
    ('meat', 'highly_perishable', 'Refrigerated or frozen storage', 5, 'kg'),
    ('packaged', 'non_perishable', 'Dry ambient shelving', 180, 'units'),
    ('beverages', 'perishable', 'Cool, dry beverage storage', 90, 'units'),
]


def seed_category_configs(apps, schema_editor):
    CategoryConfig = apps.get_model('food_management', 'CategoryConfig')
    for category, perishability, storage_guidance, shelf_life_days, default_unit in DEFAULT_CATEGORIES:
        CategoryConfig.objects.get_or_create(
            category=category,
            defaults={
                'perishability': perishability,
                'storage_guidance': storage_guidance,
                'shelf_life_days': shelf_life_days,
                'default_unit': default_unit,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('food_management', '0008_inventoryitem_unique_inventory_barcode_per_business'),
    ]

    operations = [
        migrations.AddField(
            model_name='categoryconfig',
            name='perishability',
            field=models.CharField(default='perishable', max_length=30),
        ),
        migrations.AddField(
            model_name='categoryconfig',
            name='storage_guidance',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.RunPython(seed_category_configs, migrations.RunPython.noop),
    ]
