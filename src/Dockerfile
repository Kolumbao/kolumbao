FROM python:3.8

COPY ./kolumbao /kolumbao

WORKDIR /kolumbao

RUN pip install -r ./requirements.txt

ARG FOLDER

WORKDIR /kolumbao/src

ENTRYPOINT ["python", "-m"]