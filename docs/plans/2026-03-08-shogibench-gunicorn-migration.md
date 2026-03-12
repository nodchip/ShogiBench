# ShogiBench Gunicorn Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `ShogiBench` を `manage.py runserver` から Gunicorn 起動へ切り替え、静的ファイルを本番で継続配信できる状態にする。

**Architecture:** Django の WSGI アプリは既存の `OpenSite.wsgi.application` をそのまま利用し、Gunicorn を systemd から起動する。`runserver` 依存だった静的配信は WhiteNoise に寄せ、`STATIC_ROOT` を追加して `collectstatic` 後の成果物を Gunicorn 配下で配信する。

**Tech Stack:** Django 4.2, Gunicorn, WhiteNoise, systemd

---

### Task 1: 本番設定のテストを追加する

**Files:**
- Create: `OpenBench/tests/__init__.py`
- Create: `OpenBench/tests/test_deployment_settings.py`

**Step 1: Write the failing test**

追加する確認点:
- `WhiteNoiseMiddleware` が `SecurityMiddleware` の直後に入ること
- `STATIC_ROOT` が設定されること

**Step 2: Run test to verify it fails**

Run: `python manage.py test OpenBench.tests.test_deployment_settings -v 2`
Expected: FAIL

**Step 3: Write minimal implementation**

`OpenSite/settings.py` に WhiteNoise と `STATIC_ROOT` を追加する。

**Step 4: Run test to verify it passes**

Run: `python manage.py test OpenBench.tests.test_deployment_settings -v 2`
Expected: PASS

### Task 2: Gunicorn と WhiteNoise の依存関係を追加する

**Files:**
- Modify: `requirements.txt`

**Step 1: 依存関係を追加する**

`gunicorn` と `whitenoise` を追記する。

**Step 2: 必要な環境へインストールする**

Run: `pip install -r requirements.txt`

### Task 3: ローカル検証を行う

**Files:**
- Modify: `OpenSite/settings.py`
- Modify: `requirements.txt`
- Test: `OpenBench/tests/test_deployment_settings.py`

**Step 1: build 相当確認**

Run: `python manage.py check`
Expected: `System check identified no issues`

**Step 2: test 実行**

Run: `python manage.py test OpenBench.tests.test_deployment_settings -v 2`
Expected: PASS

### Task 4: nighthawk へ反映して systemd を切り替える

**Files:**
- Server: `/etc/systemd/system/openbench.service`
- Server: `/home/nodchip/ShogiBench/.venv`

**Step 1: サーバへ依存関係を導入する**

Run: `/home/nodchip/ShogiBench/.venv/bin/pip install -r /home/nodchip/ShogiBench/requirements.txt`

**Step 2: static を収集する**

Run: `/home/nodchip/ShogiBench/.venv/bin/python3 manage.py collectstatic --noinput`

**Step 3: service を Gunicorn 起動に置換する**

`ExecStart` を `gunicorn --workers 3 --bind 0.0.0.0:8001 OpenSite.wsgi:application` に変更する。

**Step 4: 再起動して状態確認**

Run: `systemctl daemon-reload && systemctl restart openbench.service && systemctl status openbench.service --no-pager`
Expected: `active (running)`

### Task 5: 疎通確認を行う

**Files:**
- Server runtime only

**Step 1: ローカル HTTP 確認**

Run: `curl http://127.0.0.1:8001/`

**Step 2: 静的ファイル確認**

Run: `curl http://127.0.0.1:8001/static/style.css`

**Step 3: 公開経路確認**

Run: `curl -I https://bench.kishibe.dyndns.tv/`
