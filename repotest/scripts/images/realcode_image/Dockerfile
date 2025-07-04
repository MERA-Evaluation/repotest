FROM ubuntu:20.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    wget \
    bzip2 \
    curl \
    ca-certificates \
    libglib2.0-0 \
    libxext6 \
    libsm6 \
    libxrender1 \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Etc/UTC
RUN apt-get update && apt-get install -y build-essential python3-dev ffmpeg lsb-release
ENV PATH=/opt/conda/bin:$PATH

RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -O /tmp/miniconda.sh && \
    /bin/bash /tmp/miniconda.sh -b -p /opt/conda && \
    rm /tmp/miniconda.sh && \
    /opt/conda/bin/conda clean -y --all
# RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O /tmp/miniconda.sh && \
#     /bin/bash /tmp/miniconda.sh -b -p /opt/conda && \
#     rm /tmp/miniconda.sh && \
#     /opt/conda/bin/conda clean -y --all

RUN conda install -c conda-forge gdal && \
    conda install -c conda-forge conda-pack

RUN pip install --upgrade pip && echo "source /opt/conda/bin/activate" >> ~/.bashrc

WORKDIR /Realcode_eval
COPY . .

ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.1.0

# RUN pip install --no-cache-dir --no-build-isolation .[build,test]
# RUN rm -rf /Realcode_eval

WORKDIR /workspace

RUN conda create -y -n py311 python=3.11 

CMD ["/bin/bash"]
