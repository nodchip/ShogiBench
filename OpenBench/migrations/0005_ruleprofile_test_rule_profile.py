from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('OpenBench', '0004_test_result_side_stats'),
    ]

    operations = [
        migrations.CreateModel(
            name='RuleProfile',
            fields=[
                ('profile_id', models.CharField(max_length=128, primary_key=True, serialize=False)),
                ('authority_kind', models.CharField(max_length=64)),
                ('source_repository', models.CharField(max_length=1024)),
                ('source_revision', models.CharField(max_length=40)),
                ('semantics_sha256', models.CharField(max_length=64)),
                ('semantics', models.JSONField()),
            ],
        ),
        migrations.AddField(
            model_name='test',
            name='rule_profile',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='tests',
                to='OpenBench.ruleprofile',
            ),
        ),
    ]
