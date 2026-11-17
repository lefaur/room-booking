# Allure CLI для локального отчёта: в CI отчёт собирает GitHub Action, здесь та же версия генератора
FROM eclipse-temurin:21-jre-alpine
ARG ALLURE_VERSION=2.32.0
RUN apk add --no-cache bash \
 && wget -qO- "https://repo.maven.apache.org/maven2/io/qameta/allure/allure-commandline/${ALLURE_VERSION}/allure-commandline-${ALLURE_VERSION}.tgz" \
  | tar -xz -C /opt \
 && ln -s "/opt/allure-${ALLURE_VERSION}/bin/allure" /usr/local/bin/allure
WORKDIR /reports
# один HTML-файл без сервера: открывается двойным щелчком
CMD ["allure", "generate", "allure-results", "-o", "allure-report", "--clean", "--single-file"]
