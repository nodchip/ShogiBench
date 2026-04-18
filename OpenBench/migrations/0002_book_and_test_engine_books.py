from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('OpenBench', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Book',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('sha256', models.CharField(max_length=8)),
                ('name', models.CharField(max_length=64)),
                ('engine', models.CharField(max_length=64)),
                ('author', models.CharField(max_length=64)),
                ('created', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.AddField(
            model_name='test',
            name='base_book_name',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='test',
            name='base_book_sha',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
        migrations.AddField(
            model_name='test',
            name='dev_book_name',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='test',
            name='dev_book_sha',
            field=models.CharField(blank=True, default='', max_length=8),
        ),
    ]
