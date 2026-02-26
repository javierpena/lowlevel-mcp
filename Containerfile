FROM registry.access.redhat.com/ubi9/python-312:9.7

ENV SUMMARY="Low-level info MCP server" \
    DESCRIPTION="MCP server prodiving access to low-level information from the server."

LABEL name="lowlevel-mcp-server" \
      summary="${SUMMARY}" \
      description="${DESCRIPTION}" \
      io.k8s.display-name="lowlevel-mcp-server" \
      io.k8s.description="${DESCRIPTION}" \
      io.openshift.tags="mcp,python"

# Install required packages: ethtool and msr-tools from EPEL9
USER 0
RUN dnf -y install https://dl.fedoraproject.org/pub/epel/epel{,-next}-release-latest-9.noarch.rpm && dnf -y install msr-tools ethtool && dnf clean all

# Install requirements
USER 1001
COPY --chown=1001:0 requirements.txt /opt/app/requirements.txt
WORKDIR /opt/app
RUN pip install --no-cache-dir -r requirements.txt

# Copy server and associated files
COPY --chown=1001:0 *.py /opt/app/

EXPOSE 9028

WORKDIR /opt/app
ENTRYPOINT ["python", "lowlevel.py"]
