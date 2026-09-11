from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('OpenBench', '0005_ruleprofile_test_rule_profile')]
    operations = [
        migrations.AddField(
            model_name='result', name='illegal_moves',
            field=models.IntegerField(default=0),
        ),
    ]
