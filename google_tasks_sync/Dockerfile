ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG C.UTF-8

# Install dependencies
RUN apk add --no-cache \
    python3 \
    py3-pip \
    jq \
    curl

WORKDIR /app

# Install python dependencies
COPY app/requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy application files
COPY app/ /app/
COPY run.sh /

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
