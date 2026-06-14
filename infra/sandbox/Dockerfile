FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim@sha256:bebc7d6de6dd015a483903461eaedea12805728be6f9a044ca7106a2f7e11ddf

RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system \
    pandas \
    openpyxl \
    numpy \
    pymupdf \
    markitdown \ 
    pyyaml

CMD ["python"]