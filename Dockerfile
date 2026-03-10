FROM gcr.io/oss-fuzz-base/base-image


ARG arch=x86_64


RUN unset   CXX CC CXXFLAGS CFLAGS

# Install newer cmake.
ENV CMAKE_VERSION 3.26.4
RUN apt-get update && apt-get install -y wget sudo && \
    wget -q https://github.com/Kitware/CMake/releases/download/v$CMAKE_VERSION/cmake-$CMAKE_VERSION-Linux-$arch.sh && \
    chmod +x cmake-$CMAKE_VERSION-Linux-$arch.sh && \
    ./cmake-$CMAKE_VERSION-Linux-$arch.sh --skip-license --prefix="/usr/local" && \
    rm cmake-$CMAKE_VERSION-Linux-$arch.sh && \
    SUDO_FORCE_REMOVE=yes apt-get autoremove --purge -y wget sudo && \
    rm -rf /usr/local/doc/cmake /usr/local/bin/cmake-gui


RUN apt-get update && \
    apt-get install -y \
        curl \
        wget \
        git \
        jq \
        patchelf \
        subversion \
        zip \
     build-essential make \
git binutils-dev zlib1g-dev \
texinfo bison flex g++-multilib  \
  vim \
  openssh-server \
  unzip \
  p7zip \
  ccache \
libtool \
automake \
  autoconf \
lsb-release \
software-properties-common gnupg\
  pkg-config \
ninja-build \
  python3 python3-distutils \
        libncurses5-dev \
        libgdbm-dev \
        libnss3-dev \
        libssl-dev \
        libsqlite3-dev \
        libreadline-dev \
        libffi-dev \
        libbz2-dev \
        liblzma-dev \
        python3-pip \
python2-minimal



RUN update-alternatives --install /usr/bin/python python /usr/bin/python2 2 &&  update-alternatives --install /usr/bin/python python /usr/bin/python3 1


#RUN ln -s /usr/bin/python3 /usr/bin/python
## change python3
RUN wget https://bootstrap.pypa.io/pip/2.7/get-pip.py -O /tmp/get-pip2.py &&  wget https://bootstrap.pypa.io/pip/3.8/get-pip.py -O /tmp/get-pip.py && python3 /tmp/get-pip.py  &&   python3 -m pip install prettytable jmespath backoff && python3 -m pip  install -v --no-cache-dir \
    six==1.15.0 && python2 /tmp/get-pip2.py  && python2 -m pip install prettytable jmespath backoff && python2 -m pip  install -v six==1.15.0  && rm -rf /tmp/*

#============================================================
# Adding cuda path for default admin user: ntcadmin
#============================================================
RUN echo "export PATH=/usr/local/cuda/bin:/usr/local/nvidia/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" >> /etc/profile &&  echo "export LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/nvidia/lib64:/usr/lib64:/usr/local/lib:/usr/lib:/usr/lib/x86_64-linux-gnu" >> /etc/profile



WORKDIR $SRC/

RUN git clone -b llvmorg-16.0.0 --depth 1 https://github.com/llvm/llvm-project.git $SRC/llvm-project

RUN   cmake -G Ninja \
      -DCMAKE_BUILD_TYPE=Release \
      -DLLVM_TARGETS_TO_BUILD="X86" \
      -DLLVM_ENABLE_PROJECTS="clang;lld;" \
      -DLLVM_ENABLE_RUNTIMES="libcxx;libcxxabi;compiler-rt" \
      -DLLVM_BINUTILS_INCDIR="/usr/include/" \
 -DLLVM_BUILD_TESTS=off \
 -DLLVM_INCLUDE_TESTS=off \
    -DCOMPILER_RT_INCLUDE_TESTS=OFF \
      $SRC/llvm-project/llvm && \
  ninja  &&  ninja  install && rm -fr $SRC/llvm-project



# https://stackoverflow.com/questions/43878953/how-does-one-detect-if-one-is-running-within-a-docker-container-within-python
ENV AM_I_IN_A_DOCKER_CONTAINER="Yes"  CC="clang"  CXX="clang++" CCC="clang++" ARCHITECTURE="x86_64"


#============================================================
# Ssh settings
#============================================================
#ENV NOTVISIBLE "in users profile"
RUN mkdir /var/run/sshd && echo "export VISIBLE=now" >> /etc/profile
#============================================================
# Port exposing and ssh running
#============================================================
EXPOSE 22 6379


RUN    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git /work/depot_tools.git && ln -s /work/depot_tools.git /work/depot_tools


RUN apt-get install -y libgtest-dev && cd /usr/src/gtest && cmake CMakeLists.txt && make  && cp lib/*.a /usr/lib


# ────────────────────────────── Cron ──────────────────────────────────
# Install cron and register the log-truncation jobs from add_cron.sh
RUN apt-get update -yq && \
    apt-get install -yq --no-install-recommends cron && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN printf \
'*/30 * * * * root find /out/**/logs -maxdepth 1 -type f -name '"'"'*.log'"'"' -size +10M -exec truncate --size 0 {} +\n'\
'*/30 * * * * root find /out/**/logs -maxdepth 1 -type f -name '"'"'*.msg'"'"' -size +10M -exec truncate --size 0 {} +\n'\
    > /etc/cron.d/defects4c-logrotate && \
    chmod 0644 /etc/cron.d/defects4c-logrotate && \
    crontab /etc/cron.d/defects4c-logrotate

# ────────────────────────────── Redis ─────────────────────────────────
# Install redis and lay down the custom config
RUN apt-get update -yq && \
    apt-get install -yq --no-install-recommends redis-server && \
    apt-get clean && rm -rf /var/lib/apt/lists/*



# ── Packages ──
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update -yq && \
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

# ── Googletest ──
RUN git clone -q --depth 1 -b release-1.12.1 https://github.com/google/googletest.git /tmp/googletest && \
    cmake -S /tmp/googletest -B /tmp/googletest/build -GNinja \
          -DBUILD_SHARED_LIBS=ON -DINSTALL_GTEST=ON && \
    cmake --build /tmp/googletest/build && \
    cmake --install /tmp/googletest/build && \
    rm -rf /tmp/googletest && ldconfig

# ── Python / uv ──
RUN mkdir -p /src && \
    if [ ! -d /src/.venv ]; then \
      pip3 install -q uv && \
      cd /src && uv venv --allow-existing; \
    fi && \
    . /src/.venv/bin/activate && \
    uv pip install \
      numpy cmake_format jinja2 pandas openai rich fastapi uvicorn jmespath \
      pytest pytest-asyncio pytest-tornasync pytest-trio pytest-twisted \
      anyio twisted redis asyncio requests gunicorn

# ───────────────────────────────────────────────────────────────────────────────────────

RUN apt-get update && \
    rm -rf /tmp/* && \
    apt-get autoremove --purge -y &&\
    rm -rf /var/lib/apt/lists/* && \
     rm -rf /var/cache/apt/*  && \
     rm -rf /usr/local/python*  && \
     rm -rf /usr/local/pip*  && \
        rm -fr $SRC/

# ────────────────────────────── Redis config & warm-up data ───────────
RUN mkdir -p /src/build_tools

COPY defectsc_tpl/build_tools/redis.conf /etc/redis/redis.conf

# Ensure redis.conf's  dir  points to /var/lib/redis where dump.rdb lives.
# The source conf had  dir /src/build_tools  which would cause Redis to start
# with an empty keyspace even though the RDB file exists.
RUN sed -i 's|^dir .*|dir /var/lib/redis|' /etc/redis/redis.conf && \
    # Docker has no systemd/upstart — "supervised auto" makes Redis exit immediately.
    sed -i 's|^supervised .*|supervised no|' /etc/redis/redis.conf && \
    # Write logs to a file so failures are visible; "" sends to stdout which vanishes.
    sed -i 's|^logfile .*|logfile /var/log/redis/redis-server.log|' /etc/redis/redis.conf && \
    # Ensure Redis owns its data and log directories at build time.
    mkdir -p /var/lib/redis /var/log/redis && \
    chown -R redis:redis /var/lib/redis /var/log/redis && \
    chmod 750 /var/lib/redis /var/log/redis

# Download the pre-built RDB snapshot for warm-up.
# The file lands in /var/lib/redis/dump.rdb — update redis.conf's  dir  to match
# if it currently points elsewhere (default redis install uses /var/lib/redis).
# --location        : follow redirects (figshare issues a 302 before the file)
# --user-agent      : figshare blocks the default curl UA with a 403
# --retry           : tolerate transient network hiccups during build
# Download the pre-built RDB snapshot for warm-up from Google Drive.
# Use the direct file ID (extracted from the folder download log) so gdown
# writes straight to the target path with no subdirectory mirroring.
RUN pip3 install -q gdown && \
    gdown "https://drive.google.com/uc?id=1yxkR2IrXQ1VTkeRHzpGQ_zqwIotMLvte" \
          --output /var/lib/redis/dump.rdb && \
    chown redis:redis /var/lib/redis/dump.rdb && \
    chmod 660 /var/lib/redis/dump.rdb && \
    # Keep a pristine backup so the entrypoint can recover if a SHUTDOWN SAVE
    # later overwrites dump.rdb with an empty snapshot.
    cp /var/lib/redis/dump.rdb /var/lib/redis/dump.rdb.bak && \
    chown redis:redis /var/lib/redis/dump.rdb.bak

# ────────────────────────────── Entrypoint ────────────────────────────
RUN cat > /usr/local/bin/docker-entrypoint.sh <<'EOF'
#!/usr/bin/env bash
set -e

# ── 1. Cron ──────────────────────────────────────────────────────────
service cron start
echo "[entrypoint] cron started"

# ── 2. Redis ─────────────────────────────────────────────────────────
REDIS_CONF=/etc/redis/redis.conf
REDIS_DIR=/var/lib/redis
DUMP_FILE="${REDIS_DIR}/dump.rdb"
REDIS_LOG=/var/log/redis/redis-server.log

# Ensure correct ownership every boot (volume mounts can reset it)
chown -R redis:redis "${REDIS_DIR}" /var/log/redis
chmod 750 "${REDIS_DIR}"

# If a previous clean shutdown wrote a fresh empty dump over our data,
# restore from the build-time backup copy we stash below.
BACKUP="${REDIS_DIR}/dump.rdb.bak"
if [ -f "${BACKUP}" ] && [ ! -s "${DUMP_FILE}" ]; then
    echo "[entrypoint] dump.rdb is empty — restoring from backup"
    cp "${BACKUP}" "${DUMP_FILE}"
    chown redis:redis "${DUMP_FILE}"
fi

# Start redis as the redis user (supervised no — plain daemon mode)
su -s /bin/sh redis -c "redis-server ${REDIS_CONF}"

# Wait until Redis is actually ready — poll instead of blind sleep
echo -n "[entrypoint] Waiting for Redis to load RDB"
for i in $(seq 1 60); do
    if redis-cli ping 2>/dev/null | grep -q PONG; then
        echo ""
        break
    fi
    echo -n "."
    sleep 1
    # If Redis has already exited, dump the log and abort
    if [ $i -eq 60 ]; then
        echo ""
        echo "[entrypoint] ERROR: Redis did not start in 60s — last log lines:"
        tail -20 "${REDIS_LOG}" || true
        exit 1
    fi
done

KEYS=$(redis-cli dbsize 2>/dev/null || echo 0)
echo "[entrypoint] Redis ready — ${KEYS} keys loaded from ${DUMP_FILE}"

# Persist a backup of the warm snapshot so a later SHUTDOWN SAVE
# (which would produce an empty dump) can be recovered from on next boot.
if [ "${KEYS}" -gt 0 ] && [ ! -f "${BACKUP}" ]; then
    cp "${DUMP_FILE}" "${BACKUP}"
    chown redis:redis "${BACKUP}"
    echo "[entrypoint] Backup snapshot saved to ${BACKUP}"
fi

# ── 3. sshd (foreground — keeps the container alive) ─────────────────
exec /usr/sbin/sshd -D
EOF
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

