# © 2026 The Radiativity Company
# Licensed under the Apache License, Version 2.0
# See the LICENSE file for details.

# --- Configuration ---
PROJECTNAME := ucon-tools
PYTHON ?= 3.12
SUPPORTED_PYTHONS := 3.10 3.11 3.12 3.13 3.14
UV_VENV ?= .${PROJECTNAME}-${PYTHON}
UV_INSTALLED := .uv-installed
DEPS_INSTALLED := ${UV_VENV}/.deps-installed
TESTDIR := tests/
TESTNAME ?=
COVERAGE ?= true

# --- Color Setup ---
GREEN := \033[0;32m
CYAN := \033[0;36m
YELLOW := \033[1;33m
RESET := \033[0m

# --- Help Command ---
.PHONY: help
help:
	@echo "\n${YELLOW}ucon-tools Development Commands${RESET}\n"
	@echo "  ${CYAN}install${RESET}           - Install package with all extras"
	@echo "  ${CYAN}install-test${RESET}      - Install with test dependencies only"
	@echo "  ${CYAN}test${RESET}              - Run tests (PYTHON=X.Y for specific version)"
	@echo "  ${CYAN}test-all${RESET}          - Run tests across all supported Python versions"
	@echo "  ${CYAN}coverage${RESET}          - Generate coverage report"
	@echo "  ${CYAN}build${RESET}             - Build source and wheel distributions"
	@echo "  ${CYAN}venv${RESET}              - Create virtual environment"
	@echo "  ${CYAN}clean${RESET}             - Remove build artifacts and caches"
	@echo ""
	@echo "${YELLOW}MCP Server Commands:${RESET}\n"
	@echo "  ${CYAN}mcp-server${RESET}        - Start MCP server (foreground)"
	@echo "  ${CYAN}mcp-server-bg${RESET}     - Start MCP server (background)"
	@echo "  ${CYAN}mcp-server-stop${RESET}   - Stop background MCP server"
	@echo "  ${CYAN}mcp-server-status${RESET} - Check if MCP server is running"
	@echo ""
	@echo "${YELLOW}Variables:${RESET}\n"
	@echo "  PYTHON=${PYTHON}		- Python version for test target"
	@echo "  UV_VENV=${UV_VENV}	- Path to virtual environment"
	@echo "  TESTNAME=		- Specific test to run (e.g., tests.ucon.test_core)"
	@echo "  COVERAGE=${COVERAGE}		- Enable coverage (true/false)"
	@echo ""

# --- uv Installation ---
${UV_INSTALLED}:
	@command -v uv >/dev/null 2>&1 || { \
		echo "${GREEN}Installing uv...${RESET}"; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
	}
	@touch ${UV_INSTALLED}

# --- Virtual Environment ---
${UV_VENV}: ${UV_INSTALLED}
	@echo "${GREEN}Creating virtual environment at ${UV_VENV}...${RESET}"
	@uv venv --python ${PYTHON} ${UV_VENV}

${DEPS_INSTALLED}: pyproject.toml uv.lock | ${UV_VENV}
	@echo "${GREEN}Syncing dependencies into ${UV_VENV}...${RESET}"
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv sync --python ${PYTHON} --extra test --extra pydantic --extra mcp
	@touch ${DEPS_INSTALLED}

.PHONY: venv
venv: ${DEPS_INSTALLED}
	@echo "${CYAN}Virtual environment ready at ${UV_VENV}${RESET}"
	@echo "${CYAN}Activate with:${RESET} source ${UV_VENV}/bin/activate"

# --- Installation ---
.PHONY: install-test
install-test: ${UV_VENV}
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv sync --python ${PYTHON} --extra test

.PHONY: install
install: ${UV_VENV}
	@echo "${GREEN}Installing with all extras into ${UV_VENV}...${RESET}"
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv sync --python ${PYTHON} --extra test --extra pydantic --extra mcp

# --- Testing ---
.PHONY: test
test: ${DEPS_INSTALLED}
	@echo "${GREEN}Running tests with Python ${PYTHON}...${RESET}"
ifeq ($(COVERAGE),true)
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} coverage run --source=ucon --branch \
		--omit="**/tests/*,**/site-packages/*.py,setup.py" \
		-m pytest $(if $(TESTNAME),$(TESTNAME),${TESTDIR}) -q
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} coverage report -m
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} coverage xml
else
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} -m pytest \
		$(if $(TESTNAME),$(TESTNAME),${TESTDIR}) -q
endif

.PHONY: test-all
test-all: ${UV_INSTALLED}
	@echo "${GREEN}Running tests across all supported Python versions...${RESET}"
	@for pyver in $(SUPPORTED_PYTHONS); do \
		echo "\n${CYAN}=== Python $$pyver ===${RESET}"; \
		uv run --python $$pyver -m pytest ${TESTDIR} -q \
		|| echo "${YELLOW}Python $$pyver: FAILED or not available${RESET}"; \
	done

# --- Coverage ---
.PHONY: coverage
coverage: ${DEPS_INSTALLED}
	@echo "${GREEN}Generating coverage report...${RESET}"
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} coverage report -m
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} coverage html
	@echo "${CYAN}HTML report at htmlcov/index.html${RESET}"

# --- Documentation ---
DOCS_DEPS_INSTALLED := ${UV_VENV}/.docs-deps-installed

${DOCS_DEPS_INSTALLED}: pyproject.toml | ${UV_VENV}
	@echo "${GREEN}Installing docs dependencies...${RESET}"
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv sync --python ${PYTHON} --extra docs
	@touch ${DOCS_DEPS_INSTALLED}

# --- MCP Server ---
MCP_PID_FILE := .mcp-server.pid

.PHONY: mcp-server
mcp-server: ${DEPS_INSTALLED}
	@echo "${GREEN}Starting ucon MCP server (foreground)...${RESET}"
	@echo "${CYAN}Press Ctrl+C to stop${RESET}"
	@UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} ucon-mcp

.PHONY: mcp-server-bg
mcp-server-bg: ${DEPS_INSTALLED}
	@if [ -f ${MCP_PID_FILE} ] && kill -0 $$(cat ${MCP_PID_FILE}) 2>/dev/null; then \
		echo "${YELLOW}MCP server already running (PID: $$(cat ${MCP_PID_FILE}))${RESET}"; \
	else \
		echo "${GREEN}Starting ucon MCP server (background)...${RESET}"; \
		UV_PROJECT_ENVIRONMENT=${UV_VENV} uv run --python ${PYTHON} ucon-mcp & \
		echo $$! > ${MCP_PID_FILE}; \
		sleep 1; \
		echo "${CYAN}MCP server started (PID: $$(cat ${MCP_PID_FILE}))${RESET}"; \
	fi

.PHONY: mcp-server-stop
mcp-server-stop:
	@if [ -f ${MCP_PID_FILE} ]; then \
		PID=$$(cat ${MCP_PID_FILE}); \
		if kill -0 $$PID 2>/dev/null; then \
			echo "${GREEN}Stopping MCP server (PID: $$PID)...${RESET}"; \
			kill $$PID; \
			rm -f ${MCP_PID_FILE}; \
			echo "${CYAN}MCP server stopped${RESET}"; \
		else \
			echo "${YELLOW}MCP server not running (stale PID file)${RESET}"; \
			rm -f ${MCP_PID_FILE}; \
		fi \
	else \
		echo "${YELLOW}No MCP server PID file found${RESET}"; \
	fi

.PHONY: mcp-server-status
mcp-server-status:
	@if [ -f ${MCP_PID_FILE} ] && kill -0 $$(cat ${MCP_PID_FILE}) 2>/dev/null; then \
		echo "${GREEN}MCP server is running (PID: $$(cat ${MCP_PID_FILE}))${RESET}"; \
	else \
		echo "${YELLOW}MCP server is not running${RESET}"; \
		[ -f ${MCP_PID_FILE} ] && rm -f ${MCP_PID_FILE}; \
	fi

# --- Building ---
.PHONY: build
build: ${UV_INSTALLED}
	@echo "${GREEN}Building distributions...${RESET}"
	@uv build
	@echo "${CYAN}Distributions at dist/${RESET}"

# --- Cleaning ---
.PHONY: clean
clean:
	@echo "${GREEN}Cleaning build artifacts...${RESET}"
	@rm -rf dist/ build/ *.egg-info/
	@rm -rf ${UV_VENV} ${DEPS_INSTALLED} ${UV_INSTALLED}
	@rm -rf .uv_cache .pytest_cache htmlcov/
	@rm -f coverage.xml .coverage
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "${CYAN}Clean complete.${RESET}"

.PHONY: clean-all
clean-all: clean
	@echo "${YELLOW}Removing uv.lock...${RESET}"
	@rm -f uv.lock
