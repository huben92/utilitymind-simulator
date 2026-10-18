FROM python:3.12-slim
WORKDIR /workspace/simulator
ENV PYTHONDONTWRITEBYTECODE=1
COPY simulator/*.py ./
COPY simulator/static ./static
EXPOSE 8766
CMD ["python", "app.py", "--port", "8766"]
