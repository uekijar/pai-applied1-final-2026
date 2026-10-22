# PAI最終課題：AI連携型 自動配薬ピッキングシステム (PoC)

## 1. プロジェクト概要
本プロジェクトは、「Physical AI応用1講座」の最終課題として作成した、AI推論とロボットシミュレーションの連携を検証するための**PoC（概念実証）プロトタイプ**です。

「自然言語の曖昧な指示から、ローカルLLMが処方データを推論し、ロボットアームが自律的に物理アクションを実行する」という一連のアーキテクチャの**初期実装**として構築しました。実用化にはまだ多くの課題がありますが、推論から物理アクションまでをローカル環境でシームレスに統合する入口としての役割を果たしています。

### 主な特徴（検証した工夫点）
* **ローカル完結型のセキュア設計:** 医療情報を扱う想定で、外部APIに依存せずローカルLLMを用いた推論から制御までを完結。
* **直感的なWeb UI:** FastAPIによるブラウザチャットUIを搭載し、自然言語入力から推論中のフィードバック、ロボット稼働までをシームレスに体験可能。
* **TFを活用した確実なキャリブレーション:** ROS 2のTFを利用してアーム先端の実測座標を取得し、Gazebo空間内のオブジェクト配置ズレを防ぐ堅牢な制御を実装。

## 🎬 デモ動画
システムの実際の動作デモンストレーションは以下の動画をご覧ください。  
[![Demo Video](https://img.youtube.com/vi/hzFczgFVt0s/1.jpg)](https://youtu.be/hzFczgFVt0s)

## 2. 実行環境
* OS: Ubuntu 22.04 (WSL2 / Docker)
* ROS 2: Humble
* シミュレータ: Gazebo
* ロボットモデル: UR3e (Universal Robots)
* LLMエンジン: Ollama (例: qwen2.5-coder:7b 等のローカルモデル)
* 言語/フレームワーク: Python 3, FastAPI, HTML/JS

## 3. ファイル構成
* `bridge_server.py` : RAGチャットUIの提供、LLM推論APIの呼び出し、およびROS 2アーム制御（JointTrajectory）を統合したFastAPIサーバー。
* `spawn_objects.py` : Gazebo空間にトレイと薬を自動キャリブレーションして配置するスクリプト。
* `patients.md` : RAGが読み込む処方箋データの知識ベース（Markdown）。
* `Dockerfile` / `docker-compose.yml` : GPU対応のROS 2シミュレーション環境構築ファイル。

## 4. 起動手順

### 1. コンテナの起動とGazeboの立ち上げ
```bash
docker compose up -d --build
docker exec -it ros2_gazebo_env bash

source /opt/ros/humble/setup.bash
source /ros2_ws/install/setup.bash
ros2 launch ur_simulation_gazebo ur_sim_control.launch.py ur_type:=ur3e

```

### 2. オブジェクト配置とシステム起動

Gazeboが起動した状態で、別ターミナルから実行します。

```bash
docker exec -it ros2_gazebo_env bash
source /ros2_ws/install/setup.bash
cd /ros2_ws/src

# オブジェクトのキャリブレーション配置
python3 spawn_objects.py

# 統合システムの起動
python3 bridge_server.py

```

## 5. 使用方法

1. Windows側でLLMエンジン（Ollama）を起動しておきます。
2. Webブラウザから `http://localhost:8000` にアクセスします。
3. チャットUIに「Aさんの朝の薬を準備して」等の自然言語を入力します。
4. 推論結果がチャットに表示され、Gazebo上のアームが連動して配薬タスクを実行します。

## 6. 制作者

* OmniCampus アカウント名: hirofumi2
