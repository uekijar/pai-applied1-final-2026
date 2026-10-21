FROM osrf/ros:humble-desktop-full

# インストール時の対話プロンプトを無効化
ENV DEBIAN_FRONTEND=noninteractive

# パッケージリストを更新し、必要なツールをインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    git \
    wget \
    ros-humble-gazebo-ros-pkgs \
    ros-humble-moveit \
    ros-humble-ur \
    ros-humble-xacro \
    && rm -rf /var/lib/apt/lists/*

# 既存ローカルRAGと連携するためのAPIツール
RUN pip3 install --no-cache-dir fastapi uvicorn requests

WORKDIR /ros2_ws
RUN echo "source /opt/ros/humble/setup.bash" >> ~/.bashrc