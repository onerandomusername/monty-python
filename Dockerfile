FROM python:3.10-slim
COPY --from=ghcr.io/astral-sh/uv:0.8.19 /uv /uvx /bin/

WORKDIR /bot

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

# Ensure installed tools can be executed out of the box
ENV UV_TOOL_BIN_DIR=/usr/local/bin

# Set SHA build argument
ARG git_sha=""
ENV GIT_SHA=$git_sha

# as we have a git dep, install git
RUN apt update && apt install git -y


# Install the project's dependencies using the lockfile and settings
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev

# Then, add the rest of the project source code and install it
# Installing separately from its dependencies allows optimal layer caching
COPY . /bot
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/bot/.venv/bin:$PATH"


ENTRYPOINT ["python3", "-m", "monty"]
