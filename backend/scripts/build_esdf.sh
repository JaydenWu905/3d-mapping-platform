#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VOXBLOX_WS="$SCRIPT_DIR/esdf_cpp/third_party/voxblox_ws"
BUILD_DIR="$SCRIPT_DIR/esdf_cpp/build"

echo "[build] 1. 安装系统依赖 (需要 sudo 权限)..."
sudo apt-get update
sudo apt-get install -y build-essential cmake git libeigen3-dev libprotobuf-dev protobuf-compiler libgoogle-glog-dev libgflags-dev libpcl-dev python3-wstool python3-yaml

echo "[build] 2. 准备 Voxblox 源码及依赖..."
if [ ! -d "$VOXBLOX_WS/src/voxblox" ]; then
    mkdir -p "$VOXBLOX_WS/src"
    cd "$VOXBLOX_WS/src"
    
    echo "尝试从国内镜像克隆主仓库..."
    git clone --depth=1 https://ghfast.top/https://github.com/ethz-asl/voxblox.git
    
    cd voxblox
    echo "替换子依赖的 GitHub 链接为国内镜像..."
    sed -i 's|https://github.com/|https://ghfast.top/https://github.com/|g' voxblox_https.rosinstall
    
    echo "剔除不需要的 catkin_grpc 依赖 (避免拉取巨大的 grpc 源码)..."
    python3 -c "
import yaml
with open('voxblox_https.rosinstall', 'r') as f:
    data = yaml.safe_load(f)
data = [x for x in data if x.get('git', {}).get('local-name') != 'catkin_grpc']
with open('voxblox_https.rosinstall', 'w') as f:
    yaml.safe_dump(data, f, default_flow_style=False)
"
    
    echo "使用 wstool 拉取子依赖..."
    wstool init . ./voxblox_https.rosinstall
    wstool update
fi

echo "[build] 3. 编译 Voxblox..."
cd "$VOXBLOX_WS"
# 优先使用 colcon（ROS2 环境），如果没有则使用 catkin（ROS1 环境）
if command -v colcon &> /dev/null; then
    echo "检测到 colcon，使用 colcon 编译 voxblox..."
    colcon build --packages-select voxblox --cmake-args -DCMAKE_BUILD_TYPE=Release
elif command -v catkin &> /dev/null; then
    echo "检测到 catkin，使用 catkin 编译 voxblox..."
    catkin init
    catkin config --cmake-args -DCMAKE_BUILD_TYPE=Release
    catkin build voxblox
else
    echo "错误: 未找到 colcon 或 catkin。请先安装 ROS 环境或运行 'sudo apt install python3-catkin-tools'"
    exit 1
fi

echo "[build] 4. 编译 voxel_points_to_esdf..."
cd "$SCRIPT_DIR/esdf_cpp"
rm -rf build && mkdir -p build && cd build
# 将编译好的 voxblox 路径传给我们的 CMakeLists
export VOXBLOX_WS="$VOXBLOX_WS"
export CMAKE_PREFIX_PATH="$VOXBLOX_WS/install:$VOXBLOX_WS/devel:$CMAKE_PREFIX_PATH"

cmake .. -DCMAKE_BUILD_TYPE=Release -DVOXBLOX_WS="$VOXBLOX_WS"
make -j$(nproc)

echo "[build] 全部编译完成！可执行文件位于: $SCRIPT_DIR/esdf_cpp/build/voxel_points_to_esdf"