FROM busybox:1.37.0

COPY assets/ /srv/assets/
COPY levels/ /srv/levels/
COPY scripts/ /srv/scripts/
COPY web/ /srv/web/
COPY index.html Qungeon.py /srv/

EXPOSE 8000

CMD ["httpd", "-f", "-p", "8000", "-h", "/srv"]