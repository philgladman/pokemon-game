FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl build-essential pkg-config bison flex libpng-dev \
    libsdl2-dev libgl-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fL --retry 3 https://codeload.github.com/gbdev/rgbds/tar.gz/refs/tags/v1.0.4 -o rgbds.tar.gz \
    && echo '8608aa597bed638f37af6d1cc0752d5e1e02c549f28e3c887fb3e7326cc06351  rgbds.tar.gz' | sha256sum -c - \
    && mkdir rgbds && tar xzf rgbds.tar.gz -C rgbds --strip-components=1 \
    && make -C rgbds -j2 && make -C rgbds install
RUN curl -fL --retry 3 https://codeload.github.com/LIJI32/SameBoy/tar.gz/refs/tags/v1.0.4 -o sameboy.tar.gz \
    && echo '5786552a51e3d1d26d768eec65485b5e8bebd4dc295fbd6194026edec1b7d474  sameboy.tar.gz' | sha256sum -c - \
    && mkdir sameboy && tar xzf sameboy.tar.gz -C sameboy --strip-components=1 \
    && make -C sameboy CONF=release -j2 sdl
RUN curl -fL --retry 3 https://codeload.github.com/novnc/noVNC/tar.gz/refs/tags/v1.6.0 -o novnc.tar.gz \
    && echo '5066103959ef4e9b10f37e5a148627360dd8414e4cf8a7db92bdbd022e728aaa  novnc.tar.gz' | sha256sum -c - \
    && mkdir novnc && tar xzf novnc.tar.gz -C novnc --strip-components=1

FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsdl2-2.0-0 libpng16-16t64 libgl1 libgl1-mesa-dri xvfb x11vnc x11-utils \
    pulseaudio pulseaudio-utils nginx python3 python3-websockets python3-xlib websockify \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home player \
    && mkdir -p /profile /rom /run/user/1000 /tmp/.X11-unix \
    && chmod 1777 /tmp/.X11-unix \
    && chown player:player /profile /run/user/1000 && chmod 700 /run/user/1000
COPY --from=build /src/sameboy/build/bin/SDL /opt/sameboy
COPY --from=build /src/rgbds/LICENSE /usr/share/doc/rgbds/LICENSE
COPY --from=build /src/novnc /opt/novnc
COPY . /app
ENV HOME=/profile XDG_DATA_HOME=/profile/.local/share XDG_CONFIG_HOME=/profile/.config \
    XDG_RUNTIME_DIR=/run/user/1000 DISPLAY=:99 SDL_AUDIODRIVER=pulseaudio \
    PULSE_SERVER=unix:/run/user/1000/pulse/native LIBGL_ALWAYS_SOFTWARE=1
USER player
WORKDIR /profile
EXPOSE 8081
CMD ["python3", "/app/run.py"]
