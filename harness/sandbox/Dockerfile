# Per-sample sandbox for the conflict-resolution agent.
# Contains only Python + javalang + the check_java script; the sample's four files
# (tagged conflict file + sides/{base,left,right}) are written in by Inspect at sample start.
# No repository code, no data, no credentials. Runtime: no network (see compose.yaml).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

RUN pip install --no-cache-dir javalang==0.13.0 six==1.17.0 \
    && useradd --create-home --uid 1000 --shell /bin/bash agent \
    && mkdir /workspace \
    && chown agent:agent /workspace

COPY check_java.py validate.py /opt/harness/

USER agent
WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
