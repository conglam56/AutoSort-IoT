FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /src
COPY backend/pom.xml backend/pom.xml
RUN mvn -B -f backend/pom.xml dependency:go-offline
COPY backend/src backend/src
COPY dashboard dashboard
RUN mvn -B -f backend/pom.xml -DskipTests package

FROM eclipse-temurin:21-jre-noble
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv libgomp1 && rm -rf /var/lib/apt/lists/*
COPY cloud-ai/requirements.txt /tmp/ai-requirements.txt
RUN python3 -m venv /opt/ai && /opt/ai/bin/pip install --no-cache-dir -r /tmp/ai-requirements.txt && rm /tmp/ai-requirements.txt
RUN useradd --system --uid 10001 --create-home autosort
WORKDIR /app
COPY --from=build --chown=autosort:autosort /src/backend/target/autosort-backend-1.0.0.jar app.jar
COPY --chown=autosort:autosort cloud-ai/worker.py cloud-ai/inference.py cloud-ai/
# Directory exists even before the team supplies a model.
COPY --chown=autosort:autosort cloud-ai/model/ cloud-ai/model/
ENV PYTHON_BIN=/opt/ai/bin/python AI_WORKER_PATH=/app/cloud-ai/worker.py AI_MODEL_DIR=/app/cloud-ai/model PYTHONDONTWRITEBYTECODE=1
ENV JAVA_TOOL_OPTIONS="-Xms32m -Xmx160m -XX:+UseSerialGC -XX:MaxMetaspaceSize=128m -XX:ReservedCodeCacheSize=48m -XX:MaxDirectMemorySize=16m -Xss512k"
USER autosort
EXPOSE 8000
ENTRYPOINT ["java", "-jar", "/app/app.jar"]
