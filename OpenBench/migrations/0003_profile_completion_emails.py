from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('OpenBench', '0002_book_and_test_engine_books'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='completion_emails',
            field=models.BooleanField(default=False),
        ),
    ]
