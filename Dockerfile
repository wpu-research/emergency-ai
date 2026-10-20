# Statik tanıtım sitesi: docs/ altındaki sayfaları tam HTML belgesine sarıp nginx ile sunar.
FROM nginx:1.27-alpine
ENV PORT=8080
COPY docs/ /tmp/docs/
RUN for f in architecture simulation; do \
      { echo '<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body style="margin:0">'; \
        cat /tmp/docs/$f.html; echo '</body></html>'; } > /usr/share/nginx/html/$f.html; \
    done && cp /usr/share/nginx/html/architecture.html /usr/share/nginx/html/index.html && rm -rf /tmp/docs
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
