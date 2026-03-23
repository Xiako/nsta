.PHONY: build run stop restart logs clean

build:
	docker build -t nsta-bot .

run:
	docker run -d --name nsta-bot --restart unless-stopped --env-file .env nsta-bot

stop:
	docker stop nsta-bot
	docker rm nsta-bot

restart: stop run

logs:
	docker logs -f nsta-bot

clean: stop
	docker rmi nsta-bot