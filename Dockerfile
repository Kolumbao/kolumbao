FROM python:3.8

WORKDIR /bot

COPY requirements.txt requirements.txt

RUN pip install -r requirements.txt

ARG FOLDER

COPY ./src/core ./core
COPY ./src/$FOLDER ./$FOLDER

ENTRYPOINT ["python", "-m"]