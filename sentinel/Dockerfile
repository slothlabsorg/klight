FROM busybox:stable-uclibc

COPY sentinel.sh /sentinel.sh
RUN chmod +x /sentinel.sh

ENTRYPOINT ["/sentinel.sh"]
