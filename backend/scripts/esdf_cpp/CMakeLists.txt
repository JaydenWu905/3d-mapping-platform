cmake_minimum_required(VERSION 3.10)
project(voxel_points_to_esdf CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Eigen3 REQUIRED)
find_package(Protobuf REQUIRED)

# glog 和 gflags 兼容处理
find_package(glog QUIET)
if(NOT glog_FOUND)
    set(GLOG_INCLUDE_DIR "/usr/include")
    set(GLOG_LIBRARY "/usr/lib/x86_64-linux-gnu/libglog.so")
else()
    set(GLOG_INCLUDE_DIR ${glog_INCLUDE_DIRS})
    set(GLOG_LIBRARY ${glog_LIBRARIES})
endif()

find_package(gflags QUIET)
if(NOT gflags_FOUND)
    set(GFLAGS_INCLUDE_DIR "/usr/include")
    set(GFLAGS_LIBRARY "/usr/lib/x86_64-linux-gnu/libgflags.so")
else()
    set(GFLAGS_INCLUDE_DIR ${gflags_INCLUDE_DIRS})
    set(GFLAGS_LIBRARY ${gflags_LIBRARIES})
endif()

# 寻找 Voxblox 编译产物 (兼容 colcon 的 install 和 catkin 的 devel)
if(DEFINED ENV{VOXBLOX_WS})
  set(VOXBLOX_WS "$ENV{VOXBLOX_WS}")
else()
  set(VOXBLOX_WS "/usr/local")
endif()

# 自动判断产物位置
if(EXISTS "${VOXBLOX_WS}/install/lib/libvoxblox.so")
    set(VOXBLOX_DEVEL "${VOXBLOX_WS}/install")
elseif(EXISTS "${VOXBLOX_WS}/devel/lib/libvoxblox.so")
    set(VOXBLOX_DEVEL "${VOXBLOX_WS}/devel")
else()
    # 兜底，如果既没有 install 也没有 devel，假设在 build 里找源码
    set(VOXBLOX_DEVEL "${VOXBLOX_WS}/build")
endif()

include_directories(
  ${VOXBLOX_DEVEL}/include
  ${VOXBLOX_WS}/src/voxblox/voxblox/include
  ${VOXBLOX_WS}/src/voxblox/minkindr/minkindr/include
  ${EIGEN3_INCLUDE_DIR}
  ${PROTOBUF_INCLUDE_DIRS}
  ${GLOG_INCLUDE_DIR}
  ${GFLAGS_INCLUDE_DIR}
)

link_directories(
  ${VOXBLOX_DEVEL}/lib
  /usr/lib/x86_64-linux-gnu
)

# 针对 proto 文件路径做兼容处理
if(EXISTS "${VOXBLOX_WS}/build/voxblox/compiled_proto/voxblox/Block.pb.cc")
    set(PROTO_SRCS
        "${VOXBLOX_WS}/build/voxblox/compiled_proto/voxblox/Block.pb.cc"
        "${VOXBLOX_WS}/build/voxblox/compiled_proto/voxblox/Layer.pb.cc"
    )
elseif(EXISTS "${VOXBLOX_WS}/build/voxblox/Block.pb.cc")
    set(PROTO_SRCS
        "${VOXBLOX_WS}/build/voxblox/Block.pb.cc"
        "${VOXBLOX_WS}/build/voxblox/Layer.pb.cc"
    )
else()
    set(PROTO_SRCS "")
endif()

add_executable(voxel_points_to_esdf voxel_points_to_esdf.cpp ${PROTO_SRCS})

target_link_libraries(voxel_points_to_esdf
  voxblox
  ${PROTOBUF_LIBRARIES}
  ${GLOG_LIBRARY}
  ${GFLAGS_LIBRARY}
  pthread
)