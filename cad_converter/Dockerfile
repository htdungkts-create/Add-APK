FROM debian:13-slim AS libredwg-build
ARG LIBREDWG_REF=f860b0fb76d5f8effb5a70769a3389cb1e0308c8
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates build-essential autoconf automake libtool libtool-bin \
    pkg-config gettext texinfo libpcre2-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone https://github.com/LibreDWG/libredwg.git . \
    && git checkout --detach ${LIBREDWG_REF}
RUN ./autogen.sh \
    && ./configure --enable-release --disable-bindings --disable-docs --disable-werror --prefix=/opt/libredwg \
    && make -C src -j1 \
    && make -C programs dwg2dxf -j1 \
    && make -C src install \
    && mkdir -p /opt/libredwg/bin \
    && ./libtool --mode=install /usr/bin/install -c programs/dwg2dxf /opt/libredwg/bin/dwg2dxf \
    && /opt/libredwg/bin/dwg2dxf --version | head -n 2

FROM python:3.12-slim
ARG LIBREDWG_REF=f860b0fb76d5f8effb5a70769a3389cb1e0308c8
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/libredwg/bin:${PATH}" \
    LD_LIBRARY_PATH="/opt/libredwg/lib" \
    CCL_LIBREDWG_REF="${LIBREDWG_REF}" \
    CCL_MAX_UPLOAD_MB=80 \
    CCL_CONVERT_TIMEOUT=180 \
    CCL_RESULT_DIR=/tmp/ccl_cad_results
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpcre2-8-0 zlib1g ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 ccl
COPY --from=libredwg-build /opt/libredwg /opt/libredwg
WORKDIR /app
COPY cad_converter/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY cad_converter/app ./app
RUN mkdir -p /tmp/ccl_cad_results && chown -R ccl:ccl /tmp/ccl_cad_results /app
USER ccl
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
