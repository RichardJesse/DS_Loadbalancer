.PHONY: build up down restart logs ps clean test analysis-a1 analysis-a2 analysis-a3 analysis-a4 venv

SERVER_IMAGE := ds_lb_server:latest
COMPOSE := docker-compose

# Build the server image (pulled dynamically by the load balancer at
# runtime, so it must exist locally before `up`) and the load-balancer
# image (built by docker-compose).
build:
	docker build -t $(SERVER_IMAGE) ./server
	$(COMPOSE) build

# Bring the whole stack up: creates net1, starts the load balancer, which
# in turn spawns the N initial server replicas.
up: build
	$(COMPOSE) up -d
	@echo "Load balancer is available at http://localhost:5000"

down:
	$(COMPOSE) down
	@echo "Removing any server replicas spawned by the load balancer..."
	-docker ps -a --filter "network=net1" --format '{{.Names}}' | grep -v load_balancer | xargs -r docker rm -f

restart: down up

logs:
	$(COMPOSE) logs -f load_balancer

ps:
	docker ps --filter "network=net1"

clean: down
	-docker rmi $(SERVER_IMAGE) ds_lb_loadbalancer:latest
	-docker network rm net1

# ---------------------------------------------------------------------
# Local (non-Docker) analysis: uses LB_MODE=process so the whole system
# (load balancer + replicas) runs as plain local processes. Useful for
# development or grading environments without Docker set up yet.
# ---------------------------------------------------------------------
venv:
	python -m venv analysis/.venv

test analysis-a1:
	python analysis/a1_bar_chart.py

analysis-a2:
	python analysis/a2_scalability.py

analysis-a3:
	python analysis/a3_failure_recovery.py

analysis-a4:
	python analysis/a4_hash_functions.py
