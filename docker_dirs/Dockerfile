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
RUN wget https://bootstrap.pypa.io/pip/2.7/get-pip.py -O /tmp/get-pip2.py &&  wget https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py && python3 /tmp/get-pip.py  &&   python3 -m pip install prettytable jmespath backoff && python3 -m pip  install -v --no-cache-dir \
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
EXPOSE 22
CMD ["/usr/sbin/sshd", "-D"]


RUN    git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git /work/depot_tools.git && ln -s /work/depot_tools.git /work/depot_tools 


RUN apt-get install -y libgtest-dev && cd /usr/src/gtest && cmake CMakeLists.txt && make  && cp lib/*.a /usr/lib


RUN apt-get update && \
    rm -rf /tmp/* && \
    apt-get autoremove --purge -y &&\
    rm -rf /var/lib/apt/lists/* && \
     rm -rf /var/cache/apt/*  && \
     rm -rf /usr/local/python*  && \
     rm -rf /usr/local/pip*  && \
	rm -fr $SRC/



