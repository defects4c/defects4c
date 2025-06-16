#!/usr/bin/env bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# ────────────────────────────── Packages ───────────────────────────────
apt-get update -yq && \
apt-get install -yq --no-install-recommends \
  build-essential cmake ccache curl wget git git-lfs unzip ca-certificates rsync tzdata \
  autoconf automake libtool pkg-config patchelf shellcheck default-jdk maven \
  gcc-multilib g++-multilib \
  libkrb5-dev libsasl2-dev libsasl2-modules libssl-dev libldap-dev \
  libcurl4-openssl-dev libc-ares-dev libapr1-dev libsvn-dev \
  libpcre3-dev libpcre2-dev libcmocka-dev libbenchmark-dev libboost-all-dev \
  libbrotli-dev libbz2-dev liblz4-dev libsnappy-dev libzstd-dev libgflags-dev \
  libprotobuf-dev libprotoc-dev protobuf-compiler libutf8proc-dev \
  libre2-dev libthrift-dev rapidjson-dev nlohmann-json3-dev \
  libopenmpi-dev libp4est-dev openmpi-bin numdiff \
  libsystemd-dev libspdlog-dev libpcap-dev expect iproute2 iptables iputils-ping \
  libidn2-dev libnghttp2-dev libssh-dev libssh2-1-dev librtmp-dev \
  libradospp-dev rados-objclass-dev libpsl-dev \
  qtbase5-dev libqt5core5a libqt5gui5 libqt5network5 libqt5widgets5 libqt5x11extras5-dev \
  libpng-dev libjpeg-turbo8-dev libimagequant-dev libde265-dev libwebp-dev \
  libtiff5-dev libx265-dev libheif-dev libfreetype-dev libxpm-dev libraqm-dev \
  dnsmasq-base dnsmasq-utils qemu-system-x86 qemu-utils libvirt0 libvirt-dev \
  libapparmor-dev libslang2 xterm libatm1 libxtables12 \
  meson graphviz libcpptest-dev yasm libjansson-dev libmagic-dev zlib1g-dev \
  && \
apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

# ───────────────────────────── Googletest ──────────────────────────────
git clone -q --depth 1 -b release-1.12.1 https://github.com/google/googletest.git /tmp/googletest && \
cmake -S /tmp/googletest -B /tmp/googletest/build -GNinja \
      -DBUILD_SHARED_LIBS=ON -DINSTALL_GTEST=ON && \
cmake --build /tmp/googletest/build && \
cmake --install /tmp/googletest/build && \
rm -rf /tmp/googletest && ldconfig

# ───────────────────────────── Python / uv ─────────────────────────────
if [ ! -d /src/.venv ]; then 
 cd /src/ && \
 pip3 install -q uv && \
uv venv       --allow-existing
fi 

source /src/.venv/bin/activate && \
uv pip install \
  numpy cmake_format jinja2 pandas openai rich fastapi uvicorn jmespath \
  pytest pytest-asyncio pytest-tornasync pytest-trio pytest-twisted \
  anyio twisted redis asyncio requests gunicorn


