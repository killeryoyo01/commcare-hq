# -*- coding: utf-8 -*-
# Generated by Django 1.9.11 on 2016-11-14 19:03
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data_analytics', '0007_auto_20160819_1423'),
    ]

    operations = [
        migrations.AlterField(
            model_name='maltrow',
            name='email',
            field=models.EmailField(max_length=254),
        ),
    ]
