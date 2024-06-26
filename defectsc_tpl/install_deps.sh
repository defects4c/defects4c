apt-get update 

apt-get install -yq --no-install-recommends libkrb5-dev
apt-get update && apt-get install -yq --no-install-recommends \
libcmocka-dev \
libpcre2-dev  \
libpcre3-dev  
 
apt-get -yq --no-install-recommends install doxygen vera++ zlib1g-dev libsnappy-dev \
          liblz4-dev  libunwind-dev
          




apt-get install -yq --no-install-recommends \
            libp4est-dev \
            libopenmpi-dev \
            numdiff \
            openmpi-bin 

apt-get install -yq --no-install-recommends tar wget git

# Install the latest OpenJDK.
apt-get install -yq --no-install-recommends default-jdk


# Install autotools (Only necessary if building from git repository).
apt-get install -yq --no-install-recommends autoconf libtool

# Install other Mesos dependencies.
apt-get -yq --no-install-recommends install  libcurl4-nss-dev libsasl2-dev libsasl2-modules maven libapr1-dev libsvn-dev zlib1g-dev iputils-ping
apt-get update && apt-get install -yq --no-install-recommends zlib1g-dev  \
        libbz2-dev \
        libsnappy-dev \
        libzstd-dev \
liblz4-dev      libgflags-dev


apt-get install -yq --no-install-recommends libcmocka-dev \
libpcre2-dev  \
libpcre3-dev  


apt-get install  -yq --no-install-recommends  libsystemd-dev 
  
apt-get install -yq --no-install-recommends libgtest-dev

apt-get install -yq --no-install-recommends \
      libbrotli-dev \
      libbz2-dev \
      libgflags-dev \
      liblz4-dev \
      libprotobuf-dev \
      libprotoc-dev \
      libre2-dev \
      libsnappy-dev \
      libthrift-dev \
      libutf8proc-dev \
      libzstd-dev \
      protobuf-compiler \
      rapidjson-dev \
      zlib1g-dev 




apt-get install -yq --no-install-recommends  libspdlog-dev
apt-get  install -yq --no-install-recommends libgl1 libpng16-16 libqt5core5a libqt5gui5 \
    libqt5network5 libqt5widgets5 libxml2 libvirt0 dnsmasq-base \
    dnsmasq-utils qemu-system-x86 qemu-utils libslang2 iproute2 \
    iptables iputils-ping libatm1 libxtables12 xterm 

apt-get install -yq --no-install-recommends libapparmor-dev libvirt-dev \
    libqt5x11extras5-dev  \
               libsystemd-dev \
               qtbase5-dev \
               libssl-dev 




if [ -f /etc/lsb-release ]; then
    # Ubuntu
    host_cpu=$(uname -m)
    if [ "$host_cpu" = "x86_64" ]; then
        x86_64_specific_packages="gcc-multilib g++-multilib"
    else
        x86_64_specific_packages=""
    fi

     apt-get install -yq --no-install-recommends \
            build-essential \
            cmake \
            ccache \
            curl \
            wget \
            libssl-dev \
            ca-certificates \
            git \
            git-lfs \
            $x86_64_specific_packages \
            libgtk2.0-dev \
            pkg-config \
            unzip \
            automake \
            libtool \
            autoconf \
            shellcheck \
            patchelf \
            libenchant1c2a \
            python3-pip \
            python3-enchant \
            python3-setuptools \
            libcairo2-dev \
            libpango1.0-dev \
            libglib2.0-dev \
            libgtk2.0-dev \
            libswscale-dev \
            libavcodec-dev \
            libavformat-dev \
            libgstreamer1.0-0 \
            gstreamer1.0-plugins-base \
            libusb-1.0-0-dev \
            libopenblas-dev


    if apt-cache search --names-only '^libjson-c2'| grep -q libjson-c2; then
         apt-get install -yq --no-install-recommends libjson-c2
    else
         apt-get install -yq --no-install-recommends libjson-c3
    fi
    if apt-cache search --names-only '^libpng12-dev'| grep -q libpng12; then
         apt-get install -yq --no-install-recommends libpng12-dev
    else
         apt-get install -yq --no-install-recommends libpng-dev
    fi

fi 


apt-get install -y -q --no-install-recommends \
        libbenchmark-dev \
        libboost-filesystem-dev \
        libboost-system-dev \
        libbrotli-dev \
        libbz2-dev \
        libc-ares-dev \
        libcurl4-openssl-dev \
        libgflags-dev \
        libgoogle-glog-dev \
        libidn2-dev \
        libkrb5-dev \
        libldap-dev \
        liblz4-dev \
        libnghttp2-dev \
        libprotobuf-dev \
        libprotoc-dev \
        libpsl-dev \
        libradospp-dev \
        libre2-dev \
        librtmp-dev \
        libsnappy-dev \
        libssh-dev \
        libssh2-1-dev \
        libssl-dev \
        libthrift-dev \
        libutf8proc-dev \
        libxml2-dev \
        libzstd-dev \
        nlohmann-json3-dev \
        npm \
        protobuf-compiler \
        rados-objclass-dev \
        rapidjson-dev \
        rsync \
        tzdata 


apt-get install -y -q --fix-missing -qq -o Acquire::Retries=3 \
libpcap-dev  expect  yasm libjansson-dev libmagic-dev libssl-dev \
 libjpeg-turbo8-dev libimagequant-dev libde265-dev libpng-dev libwebp-dev \
 libtiff5-dev libx265-dev libheif-dev libfreetype-dev libheif-dev libavifile-0.7-dev libxpm-dev libraqm-dev \
  meson graphviz libcpptest-dev
  



apt-get install -yq --no-install-recommends   libboost-all-dev  && apt-get autoremove -y 
apt-get clean && rm -rf /var/lib/apt/lists*




if [ ! -d /tmp/googletest ]; then 

        rm -fr /tmp/googletest
        git clone -b "release-1.12.1" https://github.com/google/googletest.git /tmp/googletest

        cd /tmp/googletest
        mkdir build && cd build

        cmake .. -GNinja -DBUILD_SHARED_LIBS=ON -DINSTALL_GTEST=ON 
        cmake --build .
        cmake --install .
        ldconfig

fi
# copy from oss-fuzz




yes| pip3 install  numpy cmake_format jinja2 pandas 

yes| pip3 install  openai  rich 





